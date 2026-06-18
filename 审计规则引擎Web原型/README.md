# 工程项目招标投标审计规则引擎 Web 原型

## 功能

- 导入规则库 Excel（默认读取 `outputs/rule_engine_v10/工程项目招标投标审计规则引擎基础库_V10.xlsx`）
- 新建审计项目
- 上传审计资料文件（txt、pdf、doc、docx）
- 使用 SQLite 保存项目、上传文件、规则库行数据、规则匹配结果
- 查看 `Rule_Master`、`Audit_Logic_Master`、`Audit_Test_Master` 等规则表
- 根据项目资料和规则库生成风险清单
- 生成审计底稿草稿
- 生成审计报告问题段落

## 运行

```bash
cd 审计规则引擎Web原型
pip install -r requirements.txt
python app.py
```

浏览器访问：

```text
http://127.0.0.1:5002
```

## 目录

```text
app.py
requirements.txt
templates/
uploads/
data/
```

## 说明

首次通过 `python app.py` 启动时，如果未导入规则库，系统会自动尝试导入当前工作区的 V10 Excel。
也可以在页面“导入规则库”中手动上传新的 `.xlsx` 规则库。
