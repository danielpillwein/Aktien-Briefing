import unittest
from unittest.mock import mock_open, patch

SCHEDULER_IMPORT_ERROR = None
try:
    import core.scheduler as scheduler
except ModuleNotFoundError as exc:
    SCHEDULER_IMPORT_ERROR = exc


class _DummyScheduler:
    def __init__(self, *args, **kwargs):
        self.running = False
        self.add_job_calls = []

    def add_job(self, func, trigger, **kwargs):
        self.add_job_calls.append(
            {
                "func": func,
                "trigger": trigger,
                "kwargs": kwargs,
            }
        )

    def start(self):
        self.running = True

    def shutdown(self, wait=False):
        self.running = False

    def get_job(self, job_id):
        return None


@unittest.skipIf(SCHEDULER_IMPORT_ERROR is not None, f"optional dependency missing: {SCHEDULER_IMPORT_ERROR}")
class TestSchedulerConfig(unittest.TestCase):
    def setUp(self):
        scheduler._scheduler = None
        scheduler._scheduler_meta = {}

    def tearDown(self):
        scheduler._scheduler = None
        scheduler._scheduler_meta = {}

    def test_load_scheduler_config_defaults_day_of_week(self):
        yaml_content = """
scheduler:
  time: "07:00"
  timezone: "Europe/Vienna"
"""
        with patch("builtins.open", mock_open(read_data=yaml_content)):
            cfg = scheduler._load_scheduler_config()

        self.assertEqual(cfg["day_of_week"], "tue-sat")

    def test_load_scheduler_config_uses_configured_day_of_week(self):
        yaml_content = """
scheduler:
  time: "07:00"
  timezone: "Europe/Vienna"
  day_of_week: "wed-fri"
"""
        with patch("builtins.open", mock_open(read_data=yaml_content)):
            cfg = scheduler._load_scheduler_config()

        self.assertEqual(cfg["day_of_week"], "wed-fri")

    def test_start_scheduler_background_passes_day_filter_to_jobs(self):
        dummy = _DummyScheduler()
        cfg = {
            "hour": 7,
            "minute": 0,
            "prep_hour": 6,
            "prep_minute": 55,
            "time_str": "07:00",
            "timezone": "Europe/Vienna",
            "day_of_week": "tue-sat",
        }

        with patch("core.scheduler._load_scheduler_config", return_value=cfg), patch(
            "core.scheduler.pytz.timezone", return_value="tz"
        ), patch("core.scheduler.BackgroundScheduler", return_value=dummy):
            scheduler.start_scheduler_background()

        self.assertEqual(len(dummy.add_job_calls), 2)
        for call in dummy.add_job_calls:
            self.assertEqual(call["trigger"], "cron")
            self.assertEqual(call["kwargs"]["day_of_week"], "tue-sat")

        status = scheduler.get_scheduler_status()
        self.assertEqual(status["configured_day_of_week"], "tue-sat")


if __name__ == "__main__":
    unittest.main()
