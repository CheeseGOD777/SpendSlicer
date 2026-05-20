import threading
from unittest.mock import MagicMock

from aws_cost_ultra.web.deps import get_ce_client


def test_same_thread_returns_cached_instance():
    sess = MagicMock()
    a = get_ce_client(sess)
    b = get_ce_client(sess)
    assert a is b


def test_different_sessions_get_different_clients():
    s1 = MagicMock()
    s2 = MagicMock()
    a = get_ce_client(s1)
    b = get_ce_client(s2)
    assert a is not b


def test_different_threads_get_different_instances():
    sess = MagicMock()
    seen: dict[str, object] = {}

    def grab(label: str):
        seen[label] = get_ce_client(sess)

    main_client = get_ce_client(sess)
    t1 = threading.Thread(target=grab, args=("t1",))
    t1.start(); t1.join()
    t2 = threading.Thread(target=grab, args=("t2",))
    t2.start(); t2.join()

    assert seen["t1"] is not main_client
    assert seen["t2"] is not main_client
    assert seen["t1"] is not seen["t2"]
