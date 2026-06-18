import io

import app as audit_app


def main():
    audit_app.ensure_default_rulebook()
    client = audit_app.app.test_client()

    assert client.get("/").status_code == 200
    assert client.get("/rules/Rule_Master").status_code == 200
    assert client.get("/rules/Audit_Logic_Master").status_code == 200
    assert client.get("/rules/Audit_Test_Master").status_code == 200

    resp = client.post(
        "/projects",
        data={"name": "Render Smoke Test 项目", "description": "部署版端到端测试"},
        follow_redirects=True,
    )
    assert resp.status_code == 200

    with audit_app.db() as conn:
        project_id = conn.execute("SELECT id FROM projects ORDER BY id DESC LIMIT 1").fetchone()["id"]

    sample_text = "该项目属于依法必须招标项目，达到招标规模标准，但未履行招标程序。评标报告资料不完整，合同签订时间接近。"
    resp = client.post(
        f"/projects/{project_id}",
        data={"file": (io.BytesIO(sample_text.encode("utf-8")), "测试资料.txt")},
        content_type="multipart/form-data",
        follow_redirects=True,
    )
    assert resp.status_code == 200
    assert client.post(f"/projects/{project_id}/generate", follow_redirects=True).status_code == 200
    assert client.get(f"/projects/{project_id}/risks").status_code == 200
    assert client.get(f"/projects/{project_id}/working-papers").status_code == 200
    assert client.get(f"/projects/{project_id}/reports").status_code == 200

    with audit_app.db() as conn:
        rule_count = conn.execute("SELECT COUNT(DISTINCT rule_code) FROM rule_rows WHERE sheet_name='Rule_Master'").fetchone()[0]
        risk_count = conn.execute("SELECT COUNT(*) FROM risk_results WHERE project_id=?", (project_id,)).fetchone()[0]

    print({"project_id": project_id, "rule_count": rule_count, "risk_count": risk_count})


if __name__ == "__main__":
    main()
