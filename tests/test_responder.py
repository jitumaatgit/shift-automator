from unittest.mock import patch, MagicMock

from responder import TermuxResponder, SMSConfig


class TestTermuxResponder:
    def test_send_sms_uses_popen_for_fire_and_forget(self):
        config = SMSConfig(
            staffing_number="12345",
            work_sim_sub_id="1",
            sms_transport="termux",
            dry_run=False,
        )
        responder = TermuxResponder(config)

        mock_proc = MagicMock()
        mock_proc.stdin = MagicMock()

        with patch("responder.subprocess.Popen", return_value=mock_proc) as mock_popen:
            responder._send_sms("12345", "CLAIM123")

        mock_popen.assert_called_once_with(
            ["termux-sms-send", "-s", "1", "-n", "12345"],
            stdin=-1,
            stdout=-3,
            stderr=-3,
            text=True,
        )
        mock_proc.stdin.write.assert_called_once_with("CLAIM123")
        mock_proc.stdin.close.assert_called_once()
