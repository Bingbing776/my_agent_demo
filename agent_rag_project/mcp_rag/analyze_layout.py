import sys
from pathlib import Path
_PROJECT_ROOT = str(Path(__file__).resolve().parent)
sys.path.insert(0, _PROJECT_ROOT)

try:
    import fitz  # PyMuPDF

    pdf_path = str(Path(_PROJECT_ROOT) / "data/documents/acl_2023_2026/data/pdfs/2024.acl-srw.34.pdf")
    
    doc = fitz.open(pdf_path)
    page = doc[0]  # 第一页
    
    print("=" * 80)
    print("使用 PyMuPDF 分析页面布局:")
    print("=" * 80)
    
    # 获取文本块
    blocks = page.get_text("dict")["blocks"]
    
    page_width = page.rect.width
    mid_point = page_width / 2
    
    print(f"页面宽度: {page_width:.2f}")
    print(f"中点位置: {mid_point:.2f}")
    print()
    
    left_blocks = []
    right_blocks = []
    
    for block in blocks:
        if block["type"] == 0:  # 文本块
            bbox = block["bbox"]
            center_x = (bbox[0] + bbox[2]) / 2
            text = block.get("text", "").strip()
            
            if text:  # 只显示有文字的块
                if center_x < mid_point:
                    left_blocks.append((bbox[1], text))  # (y坐标, 文本)
                    side = "左栏"
                else:
                    right_blocks.append((bbox[1], text))
                    side = "右栏"
                
                print(f"{side} | y={bbox[1]:5.1f} | {text[:60]}...")
    
    print("\n" + "=" * 80)
    print("正确的阅读顺序（先左栏后右栏，都按从上到下排序）:")
    print("=" * 80)
    
    # 排序
    left_blocks.sort(key=lambda x: x[0])
    right_blocks.sort(key=lambda x: x[0])
    
    full_text = []
    
    print("\n左栏内容:")
    for y, text in left_blocks[:10]:  # 只显示前10个
        print(f"  {text}")
        full_text.append(text)
    
    print("\n右栏内容:")
    for y, text in right_blocks[:10]:
        print(f"  {text}")
        full_text.append(text)
    
    doc.close()
    
except ImportError:
    print("需要安装 PyMuPDF: pip install pymupdf")
except Exception as e:
    print(f"错误: {e}")
    import traceback
    traceback.print_exc()
