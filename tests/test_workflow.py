from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parent.parent


def _workflow():
    return yaml.load(
        (ROOT / ".github" / "workflows" / "daily.yml").read_text(encoding="utf-8"),
        Loader=yaml.BaseLoader,
    )


def test_every_main_push_requests_a_forced_refresh():
    workflow = _workflow()
    push = workflow["on"]["push"]
    assert push["branches"] == ["main"]
    assert "paths-ignore" not in push

    steps = {step["name"]: step for step in workflow["jobs"]["build"]["steps"]}
    fetch = steps["Fetch and summarize news"]
    assert fetch["env"]["NEWS_FORCE_REFRESH"] == "${{ github.event_name == 'push' && '1' || '0' }}"
    assert "github.actor != 'github-actions[bot]'" in fetch["if"]


def test_daily_schedule_is_six_am_beijing_time():
    assert _workflow()["on"]["schedule"][0]["cron"] == "0 22 * * *"


def test_bot_generated_push_does_not_create_a_refresh_loop():
    steps = {step["name"]: step for step in _workflow()["jobs"]["build"]["steps"]}
    assert "github.actor != 'github-actions[bot]'" in steps["Check API key"]["if"]
    assert "github.actor != 'github-actions[bot]'" in steps["Commit new content"]["if"]


def test_generated_commit_uses_beijing_calendar_date():
    steps = {step["name"]: step for step in _workflow()["jobs"]["build"]["steps"]}
    assert "TZ=Asia/Shanghai date +%Y-%m-%d" in steps["Commit new content"]["run"]
