#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import pdfplumber
import os

pdf_files = [
    "P020240403302339643235.pdf",
    "W020240511360535151619.pdf"
]

for pdf_file in pdf_files:
    file_path = os.path.join(os.getcwd(), pdf_file)
    print(f"\n{'='*80}")
    print(f"文件: {pdf_file}")
    print(f"{'='*80}\n")
    
    try:
        with pdfplumber.open(file_path) as pdf:
            print(f"总页数: {len(pdf.pages)}\n")
            
            for i, page in enumerate(pdf.pages):
                print(f"\n--- 第 {i+1} 页 ---\n")
                text = page.extract_text()
                if text:
                    print(text)
                else:
                    print("[无法提取文本内容]")
                    
                # 尝试提取表格
                tables = page.extract_tables()
                if tables:
                    print("\n[表格内容]:")
                    for j, table in enumerate(tables):
                        print(f"\n表格 {j+1}:")
                        for row in table:
                            print(row)
    except Exception as e:
        print(f"错误: {e}")
