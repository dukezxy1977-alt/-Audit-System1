# 工程项目招标投标审计规则引擎系统

这是一个可部署到 GitHub + Render 的 Flask 网页版原型系统，用于导入工程项目招标投标审计规则库 Excel、管理审计项目、上传资料文件，并基于规则库生成风险清单、审计底稿草稿和审计报告问题段落。

## 功能

- 导入《工程项目招标投标审计规则引擎基础库_V10.xlsx》
- 查看 `Rule_Master`、`Audit_Logic_Master`、`Audit_Test_Master` 等规则表
- 新建审计项目
- 上传项目资料文件，支持 `.txt`、`.pdf`、`.docx`、`.doc`
- 基于项目资料和规则库生成风险清单
- 生成审计底稿草稿
- 生成审计报告问题段落
- 使用 SQLite 保存规则库、项目、上传文件和匹配结果

## 项目结构

```text
.
├── app.py
├── requirements.txt
├── render.yaml
├── README.md
├── .gitignore
├── data/
│   └── 工程项目招标投标审计规则引擎基础库_V10.xlsx
├── uploads/
│   └── .gitkeep
├── static/
│   └── style.css
└── templates/
    ├── base.html
    ├── index.html
    ├── import_rules.html
    ├── projects.html
    ├── project_detail.html
    ├── rules_index.html
    ├── sheet.html
    ├── risk_list.html
    ├── working_papers.html
    └── reports.html
```

## 本地运行方法

建议使用 Python 3.10+。

```bash
cd render_audit_rule_engine
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python app.py
```

默认本地端口为 `5002`：

```text
http://127.0.0.1:5002
```

如果需要指定端口：

```bash
PORT=8000 python app.py
```

## GitHub 推送方法

```bash
cd render_audit_rule_engine
git init
git add .
git commit -m "Initial audit rule engine web app"
git branch -M main
git remote add origin https://github.com/<your-name>/<your-repo>.git
git push -u origin main
```

如果本项目作为已有仓库的子目录，请在仓库根目录执行：

```bash
git add render_audit_rule_engine
git commit -m "Add audit rule engine web app"
git push
```

## Render 部署方法

### 方法一：使用 render.yaml

1. 将本项目推送到 GitHub。
2. 登录 Render。
3. 选择 `New` → `Blueprint`。
4. 选择该 GitHub 仓库。
5. Render 会读取 `render.yaml` 并创建 Web Service。

`render.yaml` 已包含：

```yaml
buildCommand: pip install -r requirements.txt
startCommand: gunicorn app:app --bind 0.0.0.0:$PORT
```

并预留了 Render Disk：

```yaml
disk:
  name: audit-rule-engine-data
  mountPath: /var/data
  sizeGB: 1
```

### 方法二：手动创建 Web Service

1. Render → `New` → `Web Service`
2. 选择 GitHub 仓库
3. Runtime 选择 Python
4. Build Command:

```bash
pip install -r requirements.txt
```

5. Start Command:

```bash
gunicorn app:app --bind 0.0.0.0:$PORT
```

6. 添加环境变量，见下一节。

## 环境变量说明

| 变量名 | 说明 | 默认值 |
|---|---|---|
| `PORT` | Web 服务端口，Render 自动提供 | `5002` |
| `SECRET_KEY` | Flask session 密钥 | `dev-audit-rule-engine` |
| `DATA_DIR` | 数据目录 | `./data` |
| `UPLOAD_DIR` | 上传文件目录 | `./uploads` |
| `DATABASE_PATH` | SQLite 数据库路径 | `./data/audit_engine.db` |
| `RULEBOOK_PATH` | 默认规则库 Excel 路径 | `./data/工程项目招标投标审计规则引擎基础库_V10.xlsx` |
| `MAX_CONTENT_LENGTH` | 最大上传大小，单位字节 | `83886080` |

Render 推荐配置：

```text
DATA_DIR=/var/data
UPLOAD_DIR=/var/data/uploads
DATABASE_PATH=/var/data/audit_engine.db
RULEBOOK_PATH=/var/data/工程项目招标投标审计规则引擎基础库_V10.xlsx
```

注意：Render 免费实例的文件系统默认不是持久化的。若需要长期保存 SQLite 和上传文件，请启用 Render Disk，并将上述路径配置到 Disk 挂载目录。

## 如何导入规则库 Excel

系统支持两种方式：

1. 默认导入：启动后如果没有当前规则库，系统会尝试读取 `RULEBOOK_PATH` 指向的 Excel 文件。
2. 页面上传：进入“导入规则库”页面，上传 `.xlsx` 文件并导入。

本项目已在 `data/` 目录放入：

```text
工程项目招标投标审计规则引擎基础库_V10.xlsx
```

本地运行时可直接使用。Render 如果使用 Disk 且 `/var/data` 是空目录，需要在页面上传一次规则库，或通过 Shell/部署流程将 Excel 放入 `/var/data`。

## 使用流程

1. 进入首页，确认规则库已导入。
2. 进入“审计项目”，创建项目。
3. 进入项目详情，上传项目资料。
4. 点击“生成风险清单”。
5. 查看“风险清单”“底稿草稿”“报告段落”。

## 说明

当前系统是原型版本，规则匹配采用可解释的关键词匹配方式，适合验证规则库结构、页面流程和数据闭环。后续可替换为更精细的 OCR、文档结构化解析、向量检索或大模型判断服务。
