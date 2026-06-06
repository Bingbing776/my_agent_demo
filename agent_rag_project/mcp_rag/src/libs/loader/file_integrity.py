"""File integrity checker for incremental ingestion.
这是一个基于 SHA256 算法的文件完整性追踪工具，专门用于支持增量数据摄入。

This module provides SHA256-based file integrity tracking to enable incremental
ingestion. Files that have been successfully processed can be skipped on
subsequent ingestion runs.
在数据处理流程中，我们可能每天都会运行脚本去读取文件夹里的文件。如果没有这个工具，脚本每次都会重新读取所有文件，即使这些文件昨天已经处理过了。这个模块通过记录“哪些文件已经处理成功”，让系统在下次运行时自动跳过这些文件，只处理新的或修改过的文件。

Design Principles:
- Idempotent: Multiple ingestion runs of the same file are safe
幂等性： 即使你不小心把同一个文件处理了多次，系统也是安全的，不会产生重复数据或报错。
- Persistent: SQLite-backed storage survives process restarts
持久化： 记录是保存在 SQLite 数据库中的。这意味着即使你的程序崩溃了或者服务器重启了，之前的处理记录依然存在，不会丢失。
- Concurrent: WAL mode enables concurrent read/write operations
并发性： 数据库使用了 WAL 模式，这意味着如果有多个程序同时运行（比如多个线程或多个服务器节点），它们可以同时读取和写入记录，而不会互相锁死。
- Graceful: Failed ingestions are tracked but don't block retries
容错性： 如果一个文件处理失败了，系统会记录下来，但不会永久封杀它。下次运行时，系统会尝试重新处理它（重试机制）。
"""

import hashlib
import sqlite3
from abc import ABC, abstractmethod
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional


class FileIntegrityChecker(ABC):
    """Abstract base class for file integrity checking.
    
    Implementations track which files have been successfully processed
    to enable incremental ingestion.
    这是一个抽象基类。你可以把它理解为一个“标准模板”或“接口”。它本身不包含具体的逻辑（比如怎么连接数据库），而是规定了任何“文件完整性检查器”必须具备哪些功能
    """
    
    @abstractmethod
    def compute_sha256(self, file_path: str) -> str:
        """Compute SHA256 hash of file.
        这个函数是系统的“指纹生成器”。它的作用是读取指定路径的文件内容，并使用 SHA256 加密哈希算法计算出一个唯一的字符串（哈希值）
        
        Args:
            file_path: Path to the file to hash.输入： 文件的完整路径
            
        Returns:
            Hexadecimal SHA256 hash string (64 characters).输出： 一个长度为 64 的十六进制字符串（即 SHA256 哈希值）
            
        Raises:
            FileNotFoundError: If file does not exist.
            IOError: If path is not a file or cannot be read.
        """
        pass
    
    @abstractmethod
    def should_skip(self, file_hash: str) -> bool:
        """Check if file should be skipped based on hash.
        这是增量摄入的“决策大脑”。当你拿到一个文件的哈希值后，你需要问系统：“我以前处理过这个哈希值的文件吗？”。这个函数就是去数据库里查询的。
        Args:
            file_hash: SHA256 hash of the file.
            
        Returns:
        如果返回 True：说明这个文件之前已经完美处理过了，且内容没变。主程序应该跳过这个文件，节省时间和资源。
        如果返回 False：说明这是一个新文件，或者文件内容变了（哈希变了），或者之前处理失败了。主程序应该继续处理这个文件。
            True if file has been successfully processed before, False otherwise.
        """
        pass
    
    @abstractmethod
    def mark_success(
        self, 
        file_hash: str, 
        file_path: str, 
        collection: Optional[str] = None
    ) -> None:
        """Mark file as successfully processed.
        当主程序成功处理完一个文件（比如数据已经写入数据库，或者文件已经上传）后，必须调用这个函数来“打卡”。
        它会将文件的哈希值、文件路径以及处理时间写入数据库，标记为“已完成”。
        Args:
            file_hash: SHA256 hash of the file.
            file_path: Original file path (for tracking).
            collection: Optional collection/namespace identifier.
            collection 参数： 这是一个可选的命名空间。比如你的系统同时处理“订单数据”和“用户数据”，你可以用这个字段来区分。这样，订单系统的检查器就不会错误地跳过用户系统的文件。
        Raises:
            RuntimeError: If database operation fails.
        """
        pass
    
    @abstractmethod
    def mark_failed(
        self, 
        file_hash: str, 
        file_path: str, 
        error_msg: str
    ) -> None:
        """Mark file processing as failed.
        这是错误追踪机制。如果处理文件的过程中发生了错误（比如文件格式不对、网络中断），调用这个函数来记录失败。
        Failed files are tracked but not skipped on subsequent runs,
        allowing retries.
        
        Args:
            file_hash: SHA256 hash of the file.
            file_path: Original file path (for tracking).
            error_msg: Error message describing the failure.
            
        Raises:
            RuntimeError: If database operation fails.
        """
        pass

    @abstractmethod
    def remove_record(self, file_hash: str) -> bool:
        """Remove an ingestion record by its file hash.
        这是一个“遗忘”或“重置”功能。它的作用是从数据库中彻底删除关于某个文件哈希值的记录。
        Args:
            file_hash: SHA256 hash identifying the record.

        Returns:
            True if a record was deleted, False if not found.
        """
        pass

    @abstractmethod
    def list_processed(
        self, collection: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """List successfully processed files.
        这是一个查询和审计功能。它允许你获取一份“已成功处理文件清单”。
        Args:
            collection: Optional collection filter.  When *None* all
                successful records are returned.

        Returns:
            List of dicts with keys: file_hash, file_path, collection,
            processed_at, updated_at.
        """
        pass


class SQLiteIntegrityChecker(FileIntegrityChecker):
    """SQLite-backed file integrity checker.
    使用 SQLite 数据库存储摄入历史，利用 WAL（Write-Ahead Logging）模式支持高并发访问，确保在多进程或多线程环境下的数据一致性。
    Stores ingestion history in a SQLite database with WAL mode for
    concurrent access.
    
    Database Schema:
        ingestion_history (
            file_hash TEXT PRIMARY KEY,文件的哈希值
            file_path TEXT NOT NULL,原始文件路径
            status TEXT NOT NULL,  -- 'success' or 'failed'仅包含 'success' 或 'failed'
            collection TEXT,可选的集合/命名空间标识。只是文件的标签
            error_msg TEXT,失败时的错误信息
            processed_at TEXT NOT NULL,首次处理时间
            updated_at TEXT NOT NULL最后更新时间
        )
    
    Args:
        db_path: Path to SQLite database file (will be created if needed).
    
    Raises:
        sqlite3.DatabaseError: If database file is corrupted.
    """
    
    def __init__(self, db_path: str):
        """Initialize checker and create database if needed.
        
        Args:
            db_path: Path to SQLite database file.
        """
        self.db_path = db_path
        self._conn = None
        self._ensure_database()
    
    def close(self) -> None:
        """Close database connection if open.每次操作均新建连接，操作后立即关闭（conn.close()），并在 finally 块中确保释放"""
        if self._conn:
            self._conn.close()
            self._conn = None
    
    def __del__(self):
        """Cleanup: close connection on deletion.
        方法确保在对象销毁时调用 close 释放数据库连接"""
        self.close()
    
    def _ensure_database(self) -> None:
        """Create database file and schema if they don't exist.
        _ensure_database 中会自动创建数据库文件所在的父目录（mkdir(parents=True, exist_ok=True)）"""
        # Create parent directories if needed
        db_file = Path(self.db_path)
        db_file.parent.mkdir(parents=True, exist_ok=True)
        
        # Connect and initialize schema
        conn = sqlite3.connect(self.db_path)
        try:
            # Enable WAL mode for concurrent access获取连接
            conn.execute("PRAGMA journal_mode=WAL")
            
            # Create table if not exists
            conn.execute("""
                CREATE TABLE IF NOT EXISTS ingestion_history (
                    file_hash TEXT PRIMARY KEY,
                    file_path TEXT NOT NULL,
                    status TEXT NOT NULL,
                    collection TEXT,
                    error_msg TEXT,
                    processed_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
            """)
            
            # Create index on status for faster queries
            # 它在 status 这一列上建立了一个“目录”通过 _ensure_database 中的 CREATE INDEX 语句，命令 SQLite 引擎自动扫描表数据并生成一个 B-Tree 结构保存在硬盘上的
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_status 
                ON ingestion_history(status)
            """)
            # 我已经把所有操作都检查完了，现在请正式保存这些更改
            conn.commit()
        finally:
            conn.close()
    
    def compute_sha256(self, file_path: str) -> str:
        """Compute SHA256 hash of file using chunked reading.
        计算文件的 SHA256 哈希值
        Uses 64KB chunks to handle large files without loading entire
        file into memory.
        使用 64KB (65536字节) 的块读取方式处理大文件，避免一次性加载到内存中导致内存溢出
        Args:
            file_path: Path to the file to hash.
            
        Returns:
            Hexadecimal SHA256 hash string (64 characters).
            
        Raises:
            FileNotFoundError: If file does not exist.
            IOError: If path is not a file or cannot be read.
        """
        path = Path(file_path)
        
        if not path.exists():
            raise FileNotFoundError(f"File not found: {file_path}")
        
        if not path.is_file():
            raise IOError(f"Path is not a file: {file_path}")
        
        # Compute hash using chunked reading
        sha256_hash = hashlib.sha256()
        
        try:
            with open(file_path, "rb") as f:
                # Read in 64KB chunks
                for chunk in iter(lambda: f.read(65536), b""):
                    sha256_hash.update(chunk)
        except Exception as e:
            raise IOError(f"Failed to read file {file_path}: {e}")
        
        return sha256_hash.hexdigest()
    
    def should_skip(self, file_hash: str) -> bool:
        """Check if file should be skipped.
        查询数据库中该哈希值的记录。
        返回值：仅当记录存在且 status='success' 时返回 True（跳过）；若状态为 failed 或记录不存在，则返回 False（需处理）。
        Only files with status='success' are skipped. Failed files
        can be retried.
        
        Args:
            file_hash: SHA256 hash of the file.
            
        Returns:
            True if file has status='success', False otherwise.
        """
        conn = sqlite3.connect(self.db_path)
        try:
            cursor = conn.execute(
                "SELECT status FROM ingestion_history WHERE file_hash = ?",
                (file_hash,)
            )
            result = cursor.fetchone()
            
            if result is None:
                return False
            
            return result[0] == "success"
        finally:
            conn.close()
    
    def mark_success(
        self, 
        file_hash: str, 
        file_path: str, 
        collection: Optional[str] = None
    ) -> None:
        """Mark file as successfully processed.
        标记文件为成功处理
        Uses INSERT OR REPLACE for idempotent operation.
        
        Args:
            file_hash: SHA256 hash of the file.
            file_path: Original file path (for tracking).
            collection: Optional collection/namespace identifier.
            
        Raises:
            RuntimeError: If database operation fails.
        """
        now = datetime.now(timezone.utc).isoformat()
        
        conn = sqlite3.connect(self.db_path)
        try:
            # Check if record exists to preserve processed_at
            cursor = conn.execute(
                "SELECT processed_at FROM ingestion_history WHERE file_hash = ?",
                (file_hash,)
            )
            result = cursor.fetchone()
            
            if result:
                # Update existing record
                conn.execute("""
                    UPDATE ingestion_history 
                    SET file_path = ?,
                        status = 'success',
                        collection = ?,
                        error_msg = NULL,
                        updated_at = ?
                    WHERE file_hash = ?
                """, (file_path, collection, now, file_hash))
            else:
                # Insert new record
                conn.execute("""
                    INSERT INTO ingestion_history 
                    (file_hash, file_path, status, collection, error_msg, processed_at, updated_at)
                    VALUES (?, ?, 'success', ?, NULL, ?, ?)
                """, (file_hash, file_path, collection, now, now))
            
            conn.commit()
        except sqlite3.Error as e:
            raise RuntimeError(f"Failed to mark success for {file_path}: {e}")
        finally:
            conn.close()
    
    def mark_failed(
        self, 
        file_hash: str, 
        file_path: str, 
        error_msg: str
    ) -> None:
        """Mark file processing as failed.
        remove_record
        Failed files are not skipped, allowing retries.
        标记文件处理失败，允许后续重试。
        Args:
            file_hash: SHA256 hash of the file.
            file_path: Original file path (for tracking).
            error_msg: Error message describing the failure.
            
        Raises:
            RuntimeError: If database operation fails.
        """
        now = datetime.now(timezone.utc).isoformat()
        
        conn = sqlite3.connect(self.db_path)
        try:
            # Check if record exists to preserve processed_at
            cursor = conn.execute(
                "SELECT processed_at FROM ingestion_history WHERE file_hash = ?",
                (file_hash,)
            )
            result = cursor.fetchone()
            
            if result:
                # Update existing record
                conn.execute("""
                    UPDATE ingestion_history 
                    SET file_path = ?,
                        status = 'failed',
                        error_msg = ?,
                        updated_at = ?
                    WHERE file_hash = ?
                """, (file_path, error_msg, now, file_hash))
            else:
                # Insert new record
                conn.execute("""
                    INSERT INTO ingestion_history 
                    (file_hash, file_path, status, collection, error_msg, processed_at, updated_at)
                    VALUES (?, ?, 'failed', NULL, ?, ?, ?)
                """, (file_hash, file_path, error_msg, now, now))
            
            conn.commit()
        except sqlite3.Error as e:
            raise RuntimeError(f"Failed to mark failure for {file_path}: {e}")
        finally:
            conn.close()

    def remove_record(self, file_hash: str) -> bool:
        """Remove an ingestion record by its file hash.
            根据文件哈希值删除摄入记录。
        Args:
            file_hash: SHA256 hash identifying the record.

        Returns:
            True if a record was deleted, False if not found.
        """
        conn = sqlite3.connect(self.db_path)
        try:
            cursor = conn.execute(
                "DELETE FROM ingestion_history WHERE file_hash = ?",
                (file_hash,),
            )
            conn.commit()
            return cursor.rowcount > 0
        except sqlite3.Error as e:
            raise RuntimeError(f"Failed to remove record {file_hash}: {e}")
        finally:
            conn.close()

    def list_processed(
        self, collection: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """List successfully processed files.
        列出所有成功处理的文件记录
        Args:
            collection: Optional collection filter.

        Returns:
            List of dicts with keys: file_hash, file_path, collection,
            processed_at, updated_at.
        """
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        try:
            query = (
                "SELECT file_hash, file_path, collection, processed_at, updated_at "
                "FROM ingestion_history WHERE status = 'success'"
            )
            params: list[str] = []
            if collection is not None:
                query += " AND collection = ?"
                params.append(collection)
            query += " ORDER BY processed_at ASC"

            cursor = conn.execute(query, params)
            return [dict(row) for row in cursor.fetchall()]
        finally:
            conn.close()
