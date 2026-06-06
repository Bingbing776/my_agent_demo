# Harness 分批运行命令

在 `meta_harness_rag` 目录下执行。队列共 **60** 条（含 gate）；`skip` / `max` 均相对**整队下标**。

**重要：** `max_tasks` 统计**每一次执行**（含 `replan-*` 修复任务）。失败会插队首 replan，多占名额；`max` 过小会在 gate 前停下（例如只到 1.14）。

---

## 队列下标速查

| 下标 | 任务 |
|------|------|
| 0 | gate.1 |
| 1–15 | 1.1 … 1.15 |
| **16** | **gate.2** |
| 17–20 | 2.1 … 2.4 |
| **21** | **gate.3** |
| 22–29 | §3/§4 交叉 |
| **30** | **gate.5** |
| 31–32 | 3.5, 3.6 |
| **33** | **gate.4** |
| 34–37 | 5.1 … 5.4 |
| **38** | **gate.6** |
| 39–46 | 6.1 … 6.8 |
| **47** | **gate.7** |
| 48–57 | 7.1 … 7.10 |
| **58** | gate.8.integration |
| **59** | gate.e2e |

---

## 推荐：精确 max + 补跑（无失败时不越界）

```powershell
# 第 0 批：gate.1 + 1.1–1.3（4 条）
python main.py --skip-tasks 0 --max-tasks 4

# 第 1 批：§1 剩余 1.4–1.15 + gate.2（13 条）
python main.py --skip-tasks 4 --max-tasks 13
# 补跑：日志未到 gate.2 时（常见：被 replan 吃掉名额，停在 1.14）
python main.py --skip-tasks 15 --max-tasks 2

# 第 2 批：§2 + gate.3（5 条）
python main.py --skip-tasks 17 --max-tasks 5
# 补跑：未到 gate.3
python main.py --skip-tasks 21 --max-tasks 1

# 第 3 批：§3/§4 交叉 + gate.5（9 条）
python main.py --skip-tasks 22 --max-tasks 9
# 补跑：未到 gate.5
python main.py --skip-tasks 30 --max-tasks 1

# 第 4 批：3.5–3.6 + gate.4 + §5（7 条）
python main.py --skip-tasks 31 --max-tasks 7
# 补跑：未到 gate.4 或 §5 未跑完
python main.py --skip-tasks 33 --max-tasks 5

# 第 5 批：gate.6 + §6 + gate.7（10 条）
python main.py --skip-tasks 38 --max-tasks 10
# 补跑：未到 gate.7
python main.py --skip-tasks 47 --max-tasks 1

# 第 6 批：§7 + gate.8 + gate.e2e（12 条）
python main.py --skip-tasks 48 --max-tasks 12
# 补跑：未到 gate.8 / gate.e2e
python main.py --skip-tasks 58 --max-tasks 2
```

---

## 省事：含 replan 缓冲的一次性 max（可能多探入下一节）

无失败时 `max` 略大，会多跑后续 1～4 条 unit；下一批 **请用表中「缓冲后 skip」**，避免重复。

| 批 | 命令 | 缓冲后下一批 skip |
|----|------|-------------------|
| 0 | `--skip-tasks 0 --max-tasks 5` | 5 |
| 1 | `--skip-tasks 4 --max-tasks 17` | 21 |
| 2 | `--skip-tasks 21 --max-tasks 7` | 28 |
| 3 | `--skip-tasks 28 --max-tasks 12` | 40 |
| 4 | `--skip-tasks 40 --max-tasks 9` | 49 |
| 5 | `--skip-tasks 49 --max-tasks 13` | 62（已无任务，勿用） |
| 6 | `--skip-tasks 48 --max-tasks 14` | — |

```powershell
# 第 0 批（+1 缓冲）
python main.py --skip-tasks 0 --max-tasks 5

# 第 1 批：§1 + gate.2（+4 缓冲，约 3 次 replan 余量）
python main.py --skip-tasks 4 --max-tasks 17

# 第 2 批：§2 + gate.3（+2；若上批用缓冲且已到 2.4，本批 skip=21）
python main.py --skip-tasks 21 --max-tasks 7

# 第 3 批：§3/§4 + gate.5（+3）
python main.py --skip-tasks 28 --max-tasks 12

# 第 4 批：§3 收尾 + gate.4 + §5（+2）
python main.py --skip-tasks 40 --max-tasks 9

# 第 5 批：gate.6 + §6 + gate.7（+3）
python main.py --skip-tasks 49 --max-tasks 13

# 第 6 批：§7 + gate.8 + gate.e2e（+2）
python main.py --skip-tasks 48 --max-tasks 14
```

> 第 6 批 `skip=48` 与第 5 批缓冲路径无关；若全程用「精确 max」链式执行，第 6 批仍用 `skip=48 --max-tasks 12`。

---

## 你上次 `skip=4 --max-tasks 14` 未跑 gate.2 的原因

- 14 次名额里含 **replan-1.4、replan-1.5、replan-delete** 等约 3 条；
- 实际只推进到 **1.14**，**gate.2（下标 16）未执行**；
- 应用 **精确 13 + 补跑 2**，或 **缓冲 17**（并注意下一批 skip）。
