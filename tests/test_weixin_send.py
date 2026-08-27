from clawbridge.channels.weixin import WeixinClient, safe_send_text


class _Response:
    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict:
        return {"ret": 0}


class _Session:
    def __init__(self) -> None:
        self.last_json = None

    def post(self, url, *, headers, json, timeout):
        self.last_json = json
        return _Response()


def test_send_text_builds_bot_finish_message() -> None:
    session = _Session()
    client = WeixinClient(session=session)
    client_id = client.send_text("token", "https://example.test", "user", "ctx", "hello")
    msg = session.last_json["msg"]
    assert msg["from_user_id"] == ""
    assert msg["to_user_id"] == "user"
    assert msg["context_token"] == "ctx"
    assert msg["client_id"] == client_id
    assert msg["message_type"] == 2
    assert msg["message_state"] == 2
    assert msg["item_list"] == [{"type": 1, "text_item": {"text": "hello"}}]


class _FailingClient:
    def __init__(self) -> None:
        self.calls = 0

    def send_text(self, token, base_url, to_user_id, context_token, text):
        self.calls += 1
        raise RuntimeError("sendmessage failed: ret=-2 errmsg=prepare failed")


def test_safe_send_text_contains_prepare_failure_without_retry() -> None:
    client = _FailingClient()
    result = safe_send_text(
        client,
        "token",
        "https://example.test",
        "user",
        "ctx",
        "hello",
        purpose="synthetic",
        outbound_kind="REPLY",
    )
    assert result is None
    assert client.calls == 1


def test_safe_send_text_logs_acceptance_as_delivery_unconfirmed(capsys) -> None:
    session = _Session()
    result = safe_send_text(
        WeixinClient(session=session),
        "token", "https://example.test", "user", "ctx", "hello",
        purpose="chat_reply_1",
        outbound_kind="REPLY",
    )
    output = capsys.readouterr().out
    assert result is not None
    assert "purpose=chat_reply_1 outbound_kind=REPLY chars=5" in output
    assert "delivery=ACCEPTED_UNCONFIRMED" in output
    assert "delivery=DELIVERED" not in output


def test_safe_send_text_hard_caps_one_unicode_message() -> None:
    session = _Session()
    safe_send_text(
        WeixinClient(session=session),
        "token", "https://example.test", "user", "ctx", "中" * 1001,
        purpose="long_reply", outbound_kind="REPLY",
    )
    sent = session.last_json["msg"]["item_list"][0]["text_item"]["text"]
    assert len(sent) <= 1000
    assert "�" not in sent
    assert "[1/" not in sent


def test_safe_send_text_does_not_log_unbounded_error_payload(capsys) -> None:
    class ErrorResponse(_Response):
        def json(self) -> dict:
            return {"ret": -1, "errmsg": "secret-message-" * 100}

    class ErrorSession(_Session):
        def post(self, url, *, headers, json, timeout):
            self.last_json = json
            return ErrorResponse()

    safe_send_text(
        WeixinClient(session=ErrorSession()),
        "token", "https://example.test", "user", "ctx", "hello",
        purpose="error", outbound_kind="REPLY",
    )
    output = capsys.readouterr().out
    assert "secret-message-" in output
    assert "secret-message-secret-message-secret-message-secret-message-secret-message-secret-message-secret-message-secret-message-secret-message-secret-message-secret-message-secret-message-secret-message" not in output
