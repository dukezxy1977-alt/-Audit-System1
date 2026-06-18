import io
from pathlib import Path

import app as audit_app


def main():
    audit_app.init_db()
    if audit_app.active_rulebook() is None:
        audit_app.import_rulebook(audit_app.DEFAULT_RULEBOOK, "工程项目招标投标审计规则引擎基础库_V10")

    client = audit_app.app.test_client()

    resp = client.get("/")
    assert resp.status_code == 200, resp.status_code

    resp = client.post(
        "/projects",
        data={"name": "Smoke Test 项目", "description": "自动化冒烟测试"},
        follow_redirects=True,
    )
    assert resp.status_code == 200, resp.status_code

    with audit_app.db() as conn:
        project_id = conn.execute("SELECT id FROM projects ORDER BY id DESC LIMIT 1").fetchone()["id"]

    sample_text = "该项目属于依法必须招标项目，达到招标规模标准，但未履行招标程序。合同签订时间接近，评标报告资料不完整。"
    resp = client.post(
        f"/projects/{project_id}",
        data={"file": (io.BytesIO(sample_text.encode("utf-8")), "测试资料.txt")},
        content_type="multipart/form-data",
        follow_redirects=True,
    )
    assert resp.status_code == 200, resp.status_code

    resp = client.post(f"/projects/{project_id}/generate", follow_redirects=True)
    assert resp.status_code == 200, resp.status_code

    for path in [
        "/rules/Rule_Master",
        f"/projects/{project_id}/risks",
        f"/projects/{project_id}/working-papers",
        f"/projects/{project_id}/reports",
    ]:
        resp = client.get(path)
        assert resp.status_code == 200, (path, resp.status_code)

    with audit_app.db() as conn:
        risk_count = conn.execute("SELECT COUNT(*) FROM risk_results WHERE project_id=?", (project_id,)).fetchone()[0]
        rule_count = conn.execute("SELECT COUNT(DISTINCT rule_code) FROM rule_rows WHERE sheet_name='Rule_Master'").fetchone()[0]

    print({"project_id": project_id, "risk_count": risk_count, "rule_count": rule_count})


if __name__ == "__main__":
    main()
