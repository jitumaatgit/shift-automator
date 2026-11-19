from config import Config, RunState, load_config


class TestConfig:
    def test_config_is_dataclass_with_attributes(self):
        config = load_config()
        assert isinstance(config, Config)
        assert config.dry_run is True
        assert config.auto_decline_threshold == -5.0
        assert config.staffing_number == ""

    def test_config_loaded_from_yaml(self):
        config = load_config("config.yaml")
        assert isinstance(config, Config)
        assert config.calendar_id == "your-email@example.com"
        assert config.auto_decline_threshold == -5.0

    def test_config_is_frozen(self):
        config = load_config()
        try:
            config.dry_run = False
            assert False, "Should have frozen Config"
        except Exception:
            pass

    def test_runstate_exists(self):
        state = RunState()
        assert state.calendar is None
        assert state.weekly_hours == 0.0

        state.weekly_hours = 12.5
        assert state.weekly_hours == 12.5

    def test_config_no_dict_access_needed(self):
        config = load_config()
        assert config.active_rules == (
            "wakefulness_gate",
            "calendar_conflict",
            "day_hours_cap",
            "post_cap_break",
            "rest_gap_sleep",
            "location_preference",
            "shift_type_preference",
            "title_preference",
            "time_of_day",
            "overnight_shift",
        )
        assert config.overnight_veto_start_hour == 0
        assert config.overnight_veto_end_hour == 6
        assert config.preferred_hours == ((6, 18),)

    def test_new_rest_gap_fields_exist(self):
        config = load_config()
        assert config.rest_gap_sleep_start == 22
        assert config.rest_gap_sleep_end == 6
        assert config.rest_gap_sleep_hours == 7.0

    def test_new_cap_fields_exist(self):
        config = load_config()
        assert config.day_hours_cap == 16.0
        assert config.post_cap_break_hours == 8.0

    def test_wakefulness_gate_fields_exist(self):
        config = load_config()
        assert config.wakefulness_gate_start == 0
        assert config.wakefulness_gate_end == 6
        assert config.wakefulness_gate_current == 5

    def test_old_rest_gap_fields_removed(self):
        config = load_config()
        assert not hasattr(config, "rest_gap_strict_hours")
        assert not hasattr(config, "rest_gap_relaxed_hours")
        assert not hasattr(config, "rest_gap_desired_start")
        assert not hasattr(config, "rest_gap_desired_end")

    def test_location_preferences_loaded(self):
        config = load_config("config.yaml")
        assert "8x8" in config.location_preferences["liked"]
        assert config.location_preferences["disliked"] == []
