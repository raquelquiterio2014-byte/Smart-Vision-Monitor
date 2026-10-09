import asyncio
import json

from fastapi.testclient import TestClient
from fastapi import WebSocketDisconnect
from backend import main


def test_health_and_dashboard():
    with TestClient(main.app) as client:
        assert client.get('/api/health').json()['status'] == 'ok'
        assert 'Smart Vision Monitor' in client.get('/').text


def test_missing_log(monkeypatch, tmp_path):
    monkeypatch.setattr(main, 'EVENT_FILE', tmp_path / 'missing.jsonl')
    assert main.events() == []


def test_history_skips_invalid_and_incomplete_records(monkeypatch, tmp_path):
    path = tmp_path / 'events.jsonl'
    path.write_bytes(b'{"track_id":1}\nnot-json\n[]\n\xff\n{"track_id":2}\n{"track_id":3}')
    monkeypatch.setattr(main, 'EVENT_FILE', path)
    assert main.events() == [{'track_id': 2}, {'track_id': 1}]
    assert main.events(1) == [{'track_id': 2}]


def test_history_limit_is_bounded(monkeypatch, tmp_path):
    path = tmp_path / 'events.jsonl'
    path.write_text(''.join(json.dumps({'track_id': i}) + '\n' for i in range(600)))
    monkeypatch.setattr(main, 'EVENT_FILE', path)
    assert len(main.events(9999)) == 500
    assert len(main.events(0)) == 1


def test_websocket_waits_for_complete_unicode_record(monkeypatch, tmp_path):
    path = tmp_path / 'events.jsonl'
    monkeypatch.setattr(main, 'EVENT_FILE', path)
    record = (json.dumps({'zone': 'Área'}, ensure_ascii=False) + '\n').encode()
    split = record.index('Á'.encode()) + 1
    ticks = 0
    received = []

    async def tick(_):
        nonlocal ticks
        ticks += 1
        if ticks == 1:
            path.write_bytes(record[:split])
        elif ticks == 2:
            with path.open('ab') as stream:
                stream.write(record[split:])
        elif ticks > 3:
            raise AssertionError('Complete event was not sent')

    class Socket:
        async def accept(self):
            pass

        async def send_json(self, event):
            received.append(event)
            raise WebSocketDisconnect()

    monkeypatch.setattr(main.asyncio, 'sleep', tick)
    asyncio.run(main.event_stream(Socket()))
    assert received == [{'zone': 'Área'}]
