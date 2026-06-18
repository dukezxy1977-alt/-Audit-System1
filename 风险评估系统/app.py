# Flask 后端应用

import json
import logging
import os
import threading
import traceback
import uuid
from datetime import datetime

from flask import Flask, render_template, request, jsonify, send_file
from werkzeug.exceptions import RequestEntityTooLarge

from rules_engine import RiskRules
from file_processor import FileProcessor
from report_generator import ReportGenerator

# 项目根目录（不依赖进程启动时的 cwd，Render 上 gunicorn 的工作目录不一定等于项目目录）
BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# 初始化 Flask 应用
app = Flask(__name__)
app.config['UPLOAD_FOLDER'] = os.path.join(BASE_DIR, 'uploads')
app.config['REPORTS_FOLDER'] = os.path.join(BASE_DIR, 'reports')
app.config['MAX_CONTENT_LENGTH'] = 50 * 1024 * 1024  # 50MB 最大文件大小
app.config['ALLOWED_EXTENSIONS'] = {'pdf', 'docx', 'doc', 'txt'}

# 质疑/异议记录存储文件
# 注意：这是单文件 JSON 存储，仅适合小规模使用。Render 免费套餐的磁盘是临时的，
# 服务重启或重新部署后这里的数据会丢失；如需长期保存，需要挂载持久磁盘或换用数据库。
DISPUTES_FILE = os.path.join(BASE_DIR, 'data', 'disputes.json')
_disputes_lock = threading.Lock()

# 证据核实记录存储文件：关键词命中只是文本层面的疑似线索，按《北京市工程项目招投标
# 证据需求库》的判断口径，真正的命中/不命中/待核实结论要核对证据后才能下。
# 本系统不具备自动理解审批文件、银行流水、IP日志等证据材料的能力，这里只是让人工
# 核对证据后，把结论登记进来，覆盖掉默认的"疑似命中"状态——结论始终是人工给出的，
# 不是算法自动判定的。
EVIDENCE_FILE = os.path.join(BASE_DIR, 'data', 'evidence.json')
_evidence_lock = threading.Lock()

# 创建上传/报告/数据文件夹（使用绝对路径，避免 Render 上工作目录不一致导致创建失败或写入失败）
os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
os.makedirs(app.config['REPORTS_FOLDER'], exist_ok=True)
os.makedirs(os.path.dirname(DISPUTES_FILE), exist_ok=True)

# 日志配置：Render 通过 stdout/stderr 采集日志，需要确保 Flask 的 logger 会输出到那里。
# 在 gunicorn 下运行时（__name__ != '__main__'），把 app.logger 接到 gunicorn 的 logger 上，
# 否则 app.logger.error/exception 的内容不会出现在 Render 日志里。
logging.basicConfig(level=logging.INFO)
gunicorn_logger = logging.getLogger('gunicorn.error')
if gunicorn_logger.handlers:
    app.logger.handlers = gunicorn_logger.handlers
    app.logger.setLevel(gunicorn_logger.level)
else:
    app.logger.setLevel(logging.INFO)

# 初始化规则引擎
risk_rules = RiskRules()


def allowed_file(filename):
    """检查文件类型是否允许"""
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in app.config['ALLOWED_EXTENSIONS']


def _load_disputes():
    if not os.path.exists(DISPUTES_FILE):
        return []
    try:
        with open(DISPUTES_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        app.logger.exception("读取质疑记录文件失败: %s", DISPUTES_FILE)
        return []


def _save_disputes(disputes):
    with open(DISPUTES_FILE, 'w', encoding='utf-8') as f:
        json.dump(disputes, f, ensure_ascii=False, indent=2)


def _load_evidence():
    if not os.path.exists(EVIDENCE_FILE):
        return []
    try:
        with open(EVIDENCE_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        app.logger.exception("读取证据记录文件失败: %s", EVIDENCE_FILE)
        return []


def _save_evidence(records):
    with open(EVIDENCE_FILE, 'w', encoding='utf-8') as f:
        json.dump(records, f, ensure_ascii=False, indent=2)


def _latest_evidence_conclusion(evidence_records, rule_id, filename):
    """同一 (rule_id, filename) 可能提交过多次证据，取最新一条的结论"""
    matches = [
        e for e in evidence_records
        if e.get('rule_id') == rule_id and e.get('filename') == filename
    ]
    if not matches:
        return None
    return max(matches, key=lambda e: e.get('created_at', ''))


def _apply_evidence_conclusions(findings, filename):
    """
    用已提交的证据核实结论覆盖关键词匹配产生的默认"疑似命中"状态。
    没有人工提交过证据的发现，状态保持 analyze() 给的默认值 'suspected'。
    """
    with _evidence_lock:
        records = _load_evidence()

    for f in findings:
        latest = _latest_evidence_conclusion(records, f['rule_id'], filename)
        if latest:
            f['status'] = {'命中': 'confirmed', '不命中': 'refuted', '待核实': 'pending_verification'}[latest['conclusion']]
            f['evidence_conclusion'] = {
                'conclusion': latest['conclusion'],
                'note': latest['note'],
                'created_at': latest['created_at']
            }
        else:
            f['evidence_conclusion'] = None
    return findings


@app.errorhandler(RequestEntityTooLarge)
def handle_file_too_large(e):
    app.logger.warning("上传文件超过大小限制 (50MB)")
    return jsonify({
        'success': False,
        'error': '文件过大，最大支持 50MB'
    }), 413


@app.route('/')
def index():
    """主页"""
    return render_template('index.html')


@app.route('/api/assess', methods=['POST'])
def assess():
    """
    评估接口
    接收上传的文件，进行风险评估
    """

    file_path = None

    try:
        # 检查文件是否存在
        if 'file' not in request.files:
            app.logger.warning("请求中未包含 'file' 字段，form keys=%s", list(request.files.keys()))
            return jsonify({
                'success': False,
                'error': '未找到文件，请确认上传表单字段名为 file'
            }), 400

        file = request.files['file']

        if file.filename == '':
            return jsonify({
                'success': False,
                'error': '文件名为空'
            }), 400

        original_filename = file.filename

        if not allowed_file(original_filename):
            return jsonify({
                'success': False,
                'error': '不支持的文件格式。支持: PDF, DOCX, DOC, TXT'
            }), 400

        # 保存文件。
        # 注意：不要用 secure_filename() 处理中文文件名 —— 它会把中文字符全部剥离，
        # 常见的中文标书文件名（如“招标文件.pdf”）会被处理成 "pdf"（连扩展名的点都没了），
        # 导致后续 file_processor 无法识别文件类型而报 400。
        # 这里只取原始文件的扩展名，磁盘上的文件名完全用程序生成的安全字符串。
        file_ext = os.path.splitext(original_filename)[1].lower()
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        save_filename = f"{timestamp}_{uuid.uuid4().hex[:8]}{file_ext}"
        file_path = os.path.join(app.config['UPLOAD_FOLDER'], save_filename)
        file.save(file_path)

        # 提取文本（同时拿到按页/段落/行划分的位置信息，用于标注风险发生的具体部位）
        try:
            text, segments = FileProcessor.extract_text(file_path)
        except (ValueError, FileNotFoundError) as e:
            # 用户可纠正的输入问题（格式不支持、空文本等）：400
            app.logger.info("文本提取被拒绝 (file=%s): %s", original_filename, e)
            return jsonify({
                'success': False,
                'error': f'文本提取失败: {str(e)}'
            }), 400
        except Exception as e:
            # 解析过程中的非预期异常，记录完整堆栈方便在 Render 日志中定位
            app.logger.exception("文本提取出现非预期异常 (file=%s)", original_filename)
            return jsonify({
                'success': False,
                'error': f'文本提取失败: {type(e).__name__}: {str(e)}'
            }), 400

        # 执行风险分析（带上文档地址，定位每项风险发现的具体部位）
        findings = risk_rules.analyze(segments, source=original_filename)

        # scope=negative_list 时只看《北京市工程建设项目招标投标负面行为清单》（BJ 开头的规则），
        # 不混入另外 45 项通用关键词规则——适合专门核查"导入招标文件，看有没有负面清单行为"
        scope = (request.form.get('scope') or 'all').strip()
        if scope == 'negative_list':
            findings = [f for f in findings if f['rule_id'].startswith('BJ')]

        # 用已提交的证据核实结论覆盖默认的"疑似命中"状态（如果有人核对过证据的话）
        findings = _apply_evidence_conclusions(findings, original_filename)

        # 生成统计
        stats = risk_rules.get_statistics(findings)

        # 计算风险评分
        risk_score = risk_rules.calculate_risk_score(findings)
        risk_level = risk_rules.get_risk_level_name(risk_score)

        # 生成报告
        html_report = ReportGenerator.generate_html_report(
            original_filename, findings, stats, risk_score, risk_level
        )

        text_report = ReportGenerator.generate_text_report(
            original_filename, findings, stats, risk_score, risk_level
        )

        excel_wb = ReportGenerator.generate_excel_report(
            original_filename, findings, stats, risk_score, risk_level
        )

        # 保存报告
        report_dir = os.path.join(app.config['REPORTS_FOLDER'], datetime.now().strftime('%Y%m%d'))
        os.makedirs(report_dir, exist_ok=True)

        report_basename = f"{timestamp}_{uuid.uuid4().hex[:8]}"
        html_path = os.path.join(report_dir, f"{report_basename}_report.html")
        txt_path = os.path.join(report_dir, f"{report_basename}_report.txt")
        xlsx_path = os.path.join(report_dir, f"{report_basename}_report.xlsx")

        with open(html_path, 'w', encoding='utf-8') as f:
            f.write(html_report)

        with open(txt_path, 'w', encoding='utf-8') as f:
            f.write(text_report)

        excel_wb.save(xlsx_path)

        # 返回结果
        return jsonify({
            'success': True,
            'data': {
                'filename': original_filename,
                'scope': scope,
                'risk_score': risk_score,
                'risk_level': risk_level,
                'stats': {
                    'total': stats['total'],
                    'by_level': stats['by_level'],
                    'high_confidence': len(stats['high_confidence'])
                },
                'findings': [
                    {
                        'rule_id': f['rule_id'],
                        'module': f['module'],
                        'name': f['name'],
                        'level': f['level'],
                        'description': f['description'],
                        'matched_keywords': f['matched_keywords'],
                        'locations': f['locations'],
                        'source': f['source'],
                        'confidence': f'{f["confidence"]:.0%}',
                        'legal_basis': f.get('legal_basis', ''),
                        'judge_code': f.get('judge_code', ''),
                        'hit_condition': f.get('hit_condition', ''),
                        'evidence_required': f.get('evidence_required', []),
                        'judge_methods': f.get('judge_methods', []),
                        'judge_caliber': f.get('judge_caliber', ''),
                        'status': f.get('status', 'suspected'),
                        'evidence_conclusion': f.get('evidence_conclusion'),
                        'recommendation': f['recommendation']
                    }
                    for f in sorted(findings, key=lambda x: x['level'])
                ],
                'advice': ReportGenerator._get_score_advice(risk_score),
                'html_report': html_report,
                'text_report': text_report,
                'report_paths': {
                    'html': html_path,
                    'txt': txt_path,
                    'xlsx': xlsx_path
                }
            }
        }), 200

    except Exception as e:
        # 任何未被预料到的异常：记录完整堆栈到日志（Render 可见），并把具体错误信息返回给前端
        app.logger.exception("评估过程出现未处理异常")
        return jsonify({
            'success': False,
            'error': f'评估过程出错: {type(e).__name__}: {str(e)}',
            'traceback': traceback.format_exc() if app.debug else None
        }), 500

    finally:
        # 清理上传的临时文件，无论成功还是失败都要清理，避免磁盘堆积
        if file_path and os.path.exists(file_path):
            try:
                os.remove(file_path)
            except OSError:
                app.logger.warning("临时文件清理失败: %s", file_path)


@app.route('/api/download_report/<report_type>')
def download_report(report_type):
    """下载报告"""

    try:
        report_dir = os.path.join(app.config['REPORTS_FOLDER'], datetime.now().strftime('%Y%m%d'))

        files = []
        if os.path.exists(report_dir):
            for f in os.listdir(report_dir):
                if f.endswith(f'report.{report_type}'):
                    files.append(f)

        if files:
            latest_file = sorted(files)[-1]
            file_path = os.path.join(report_dir, latest_file)

            return send_file(
                file_path,
                as_attachment=True,
                download_name=f"招标风险评估报告.{report_type}"
            )
        else:
            return jsonify({'error': '报告不存在'}), 404

    except Exception as e:
        app.logger.exception("下载报告失败")
        return jsonify({'error': f'下载失败: {type(e).__name__}: {str(e)}'}), 500


@app.route('/api/rules')
def get_rules():
    """获取规则清单"""

    rules_info = {}
    for rule_id, rule in risk_rules.rules.items():
        rules_info[rule_id] = {
            'module': rule['module'],
            'name': rule['name'],
            'level': rule['level'],
            'description': rule['description'],
            'legal_basis': rule.get('legal_basis', ''),
            'judge_code': rule.get('judge_code', ''),
            'hit_condition': rule.get('hit_condition', ''),
            'evidence_required': rule.get('evidence_required', []),
            'judge_methods': rule.get('judge_methods', []),
            'judge_caliber': rule.get('judge_caliber', '')
        }

    return jsonify(rules_info)


@app.route('/api/statistics')
def get_statistics():
    """获取系统统计信息"""

    return jsonify({
        'total_rules': len(risk_rules.rules),
        'by_level': {
            'A': sum(1 for r in risk_rules.rules.values() if r['level'] == 'A'),
            'B': sum(1 for r in risk_rules.rules.values() if r['level'] == 'B'),
            'C': sum(1 for r in risk_rules.rules.values() if r['level'] == 'C'),
            'D': sum(1 for r in risk_rules.rules.values() if r['level'] == 'D'),
        },
        'by_module': {}
    })


@app.route('/api/query_text', methods=['POST'])
def query_text():
    """
    即时风险查询：不上传文件，直接对一段文字做风险判定
    适合核查招标文件中某一条具体条款是否命中风险规则
    """

    data = request.get_json(silent=True) or {}
    text = (data.get('text') or '').strip()

    if not text:
        return jsonify({
            'success': False,
            'error': '请输入需要查询的文本内容'
        }), 400

    if len(text) > 20000:
        return jsonify({
            'success': False,
            'error': '查询文本过长，请控制在 2 万字以内'
        }), 400

    try:
        segments = [{'location': '查询文本', 'text': text}]
        findings = risk_rules.analyze(segments, source='手动查询')

        return jsonify({
            'success': True,
            'data': {
                'has_risk': len(findings) > 0,
                'total': len(findings),
                'findings': [
                    {
                        'rule_id': f['rule_id'],
                        'module': f['module'],
                        'name': f['name'],
                        'level': f['level'],
                        'description': f['description'],
                        'matched_keywords': f['matched_keywords'],
                        'locations': f['locations'],
                        'confidence': f'{f["confidence"]:.0%}',
                        'legal_basis': f.get('legal_basis', ''),
                        'judge_code': f.get('judge_code', ''),
                        'hit_condition': f.get('hit_condition', ''),
                        'evidence_required': f.get('evidence_required', []),
                        'judge_methods': f.get('judge_methods', []),
                        'judge_caliber': f.get('judge_caliber', ''),
                        'status': f.get('status', 'suspected'),
                        'evidence_conclusion': f.get('evidence_conclusion'),
                        'recommendation': f['recommendation']
                    }
                    for f in sorted(findings, key=lambda x: x['level'])
                ]
            }
        }), 200
    except Exception as e:
        app.logger.exception("文本风险查询出现未处理异常")
        return jsonify({
            'success': False,
            'error': f'查询失败: {type(e).__name__}: {str(e)}'
        }), 500


@app.route('/api/search_rules', methods=['GET'])
def search_rules():
    """按关键词或规则编号查询规则库说明，不涉及具体文档内容"""

    keyword = request.args.get('keyword', '')
    results = risk_rules.search_rules(keyword)

    return jsonify({
        'success': True,
        'data': {
            'total': len(results),
            'rules': results
        }
    }), 200


@app.route('/api/disputes', methods=['POST'])
def create_dispute():
    """
    对系统判定的某条风险提出质疑（人工复核标记）
    用于记录“这条判定可能不准确/需要复核”，不会生成对外的正式质疑函
    """

    data = request.get_json(silent=True) or {}
    rule_id = (data.get('rule_id') or '').strip()
    reason = (data.get('reason') or '').strip()

    if not rule_id or not reason:
        return jsonify({
            'success': False,
            'error': '提出质疑需要提供 rule_id 和 reason（异议理由）'
        }), 400

    # locations/matched_keywords 是前端附带的命中片段，用于人工复核时不用再去翻文档找上下文。
    # 限制长度和数量，防止恶意请求把存储文件撑大。
    raw_locations = data.get('locations') or []
    locations = [
        {
            'location': str(loc.get('location', ''))[:50],
            'keyword': str(loc.get('keyword', ''))[:50],
            'context': str(loc.get('context', ''))[:200]
        }
        for loc in raw_locations[:20] if isinstance(loc, dict)
    ]
    matched_keywords = [str(kw)[:50] for kw in (data.get('matched_keywords') or [])[:20]]

    dispute = {
        'id': uuid.uuid4().hex,
        'created_at': datetime.now().isoformat(timespec='seconds'),
        'rule_id': rule_id,
        'rule_name': (data.get('name') or '').strip(),
        'module': (data.get('module') or '').strip(),
        'level': (data.get('level') or '').strip(),
        'filename': (data.get('filename') or '').strip(),
        'locations': locations,
        'matched_keywords': matched_keywords,
        'reason': reason,
        'status': 'pending'
    }

    with _disputes_lock:
        disputes = _load_disputes()
        disputes.append(dispute)
        _save_disputes(disputes)

    return jsonify({'success': True, 'data': dispute}), 201


@app.route('/api/disputes', methods=['GET'])
def list_disputes():
    """查看已提出的质疑记录，可按 rule_id / filename / status 过滤"""

    rule_id = request.args.get('rule_id')
    filename = request.args.get('filename')
    status = request.args.get('status')

    with _disputes_lock:
        disputes = _load_disputes()

    if rule_id:
        disputes = [d for d in disputes if d.get('rule_id') == rule_id]
    if filename:
        disputes = [d for d in disputes if d.get('filename') == filename]
    if status:
        disputes = [d for d in disputes if d.get('status') == status]

    return jsonify({'success': True, 'data': {'total': len(disputes), 'disputes': disputes}}), 200


@app.route('/api/disputes/<dispute_id>', methods=['PATCH'])
def update_dispute(dispute_id):
    """更新质疑记录的复核状态（pending / resolved / rejected）"""

    data = request.get_json(silent=True) or {}
    status = (data.get('status') or '').strip()

    if status not in ('pending', 'resolved', 'rejected'):
        return jsonify({
            'success': False,
            'error': 'status 必须是 pending / resolved / rejected 之一'
        }), 400

    with _disputes_lock:
        disputes = _load_disputes()
        target = next((d for d in disputes if d['id'] == dispute_id), None)

        if target is None:
            return jsonify({'success': False, 'error': '未找到该质疑记录'}), 404

        target['status'] = status
        if 'review_note' in data:
            target['review_note'] = (data.get('review_note') or '').strip()
        target['updated_at'] = datetime.now().isoformat(timespec='seconds')

        _save_disputes(disputes)

    return jsonify({'success': True, 'data': target}), 200


@app.route('/api/evidence', methods=['POST'])
def submit_evidence():
    """
    提交证据核实结论。

    系统本身不能自动理解审批文件、银行流水、IP日志这类证据材料——
    这里只是让人工核对完 evidence_required 清单里的材料后，把结论登记进来，
    覆盖掉文本关键词匹配产生的默认"疑似命中"状态。conclusion 必须是
    命中 / 不命中 / 待核实 之一，对应《北京市工程项目招投标证据需求库》的判断口径。
    """

    data = request.get_json(silent=True) or {}
    rule_id = (data.get('rule_id') or '').strip()
    filename = (data.get('filename') or '').strip()
    conclusion = (data.get('conclusion') or '').strip()
    note = (data.get('note') or '').strip()

    if not rule_id or not filename:
        return jsonify({'success': False, 'error': '需要提供 rule_id 和 filename'}), 400

    if conclusion not in ('命中', '不命中', '待核实'):
        return jsonify({'success': False, 'error': 'conclusion 必须是 命中 / 不命中 / 待核实 之一'}), 400

    if not note:
        return jsonify({'success': False, 'error': '请填写证据核实说明（note），便于后续复核追溯'}), 400

    record = {
        'id': uuid.uuid4().hex,
        'created_at': datetime.now().isoformat(timespec='seconds'),
        'rule_id': rule_id,
        'rule_name': (data.get('name') or '').strip(),
        'filename': filename,
        'conclusion': conclusion,
        'note': note,
        # 核对过的证据项（从 evidence_required 清单里勾选的，仅供留痕，不强制校验完整性）
        'checked_evidence': [str(e)[:100] for e in (data.get('checked_evidence') or [])[:30]]
    }

    with _evidence_lock:
        records = _load_evidence()
        records.append(record)
        _save_evidence(records)

    return jsonify({'success': True, 'data': record}), 201


@app.route('/api/evidence', methods=['GET'])
def list_evidence():
    """查看已提交的证据核实记录，可按 rule_id / filename 过滤"""

    rule_id = request.args.get('rule_id')
    filename = request.args.get('filename')

    with _evidence_lock:
        records = _load_evidence()

    if rule_id:
        records = [e for e in records if e.get('rule_id') == rule_id]
    if filename:
        records = [e for e in records if e.get('filename') == filename]

    return jsonify({'success': True, 'data': {'total': len(records), 'evidence': records}}), 200


if __name__ == '__main__':
    # 注意：macOS 的 AirPlay 接收器（ControlCenter）默认占用 5000 端口，
    # 本地访问 127.0.0.1:5000 会被系统服务拦截并返回 403，而不是这个 Flask 应用。
    # 本地调试改用 5001，线上 Render 部署用 gunicorn + $PORT，不受此影响。
    app.run(debug=True, host='127.0.0.1', port=5001)
