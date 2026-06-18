#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
招标投标风险评估系统 - 快速启动脚本
自动安装依赖并启动应用
"""

import subprocess
import sys
import os

def main():
    print("=" * 60)
    print("🎯 招标投标风险评估系统 - 启动向导")
    print("=" * 60)
    
    # 检查 Python 版本
    if sys.version_info < (3, 8):
        print("❌ 错误：需要 Python 3.8 或更高版本")
        sys.exit(1)
    
    print(f"✓ Python 版本: {sys.version.split()[0]}")
    
    # 检查虚拟环境
    venv_path = os.path.join(os.getcwd(), 'venv')
    if not os.path.exists(venv_path):
        print("\n📦 创建虚拟环境...")
        try:
            subprocess.run([sys.executable, '-m', 'venv', 'venv'], check=True)
            print("✓ 虚拟环境创建成功")
        except subprocess.CalledProcessError:
            print("❌ 虚拟环境创建失败")
            sys.exit(1)
    else:
        print("✓ 虚拟环境已存在")
    
    # 确定虚拟环境 Python 的路径
    if sys.platform == 'win32':
        python_exec = os.path.join(venv_path, 'Scripts', 'python.exe')
        pip_exec = os.path.join(venv_path, 'Scripts', 'pip.exe')
    else:
        python_exec = os.path.join(venv_path, 'bin', 'python')
        pip_exec = os.path.join(venv_path, 'bin', 'pip')
    
    # 安装依赖
    print("\n📚 安装依赖包...")
    try:
        subprocess.run(
            [pip_exec, 'install', '-r', 'requirements.txt'],
            check=True,
            capture_output=True
        )
        print("✓ 依赖安装成功")
    except subprocess.CalledProcessError as e:
        print(f"❌ 依赖安装失败: {e}")
        sys.exit(1)
    
    # 启动应用
    print("\n🚀 启动应用...")
    print("=" * 60)
    print("📝 应用信息：")
    print("   • 地址: http://127.0.0.1:5001")
    print("   • 浏览器: 自动打开或手动访问上述地址")
    print("   • 停止: 按 Ctrl+C")
    print("=" * 60)
    print()
    
    try:
        subprocess.run(
            [python_exec, 'app.py'],
            check=True
        )
    except KeyboardInterrupt:
        print("\n\n👋 应用已停止")
    except subprocess.CalledProcessError as e:
        print(f"❌ 应用启动失败: {e}")
        sys.exit(1)

if __name__ == '__main__':
    main()
