import importlib.util
from pathlib import Path
import pytest
import io
import urllib.error
ROOT = Path(__file__).resolve().parents[1]
SCRIPT=ROOT/'tools/panel_liveness_watchdog.py'

def load():
 spec=importlib.util.spec_from_file_location('watchdog_runtime',SCRIPT);m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);return m

def test_success_resets_failure_counter(tmp_path,monkeypatch):
 m=load();state=tmp_path/'state';state.write_text('1');monkeypatch.setattr(m,'STATE_FILE',state);monkeypatch.setattr(m,'probe_live',lambda:True);called=[];monkeypatch.setattr(m,'restart_panel',lambda:called.append(1));assert m.run_once()==0;assert state.read_text()=='0';assert called==[]

def test_second_consecutive_failure_restarts_once(tmp_path,monkeypatch):
 m=load();state=tmp_path/'state';state.write_text('1');monkeypatch.setattr(m,'STATE_FILE',state);monkeypatch.setattr(m,'probe_live',lambda:False);called=[];monkeypatch.setattr(m,'restart_panel',lambda:called.append(1));assert m.run_once()==0;assert called==[1];assert state.read_text()=='0'

def test_first_failure_does_not_restart(tmp_path,monkeypatch):
 m=load();state=tmp_path/'state';monkeypatch.setattr(m,'STATE_FILE',state);monkeypatch.setattr(m,'probe_live',lambda:False);called=[];monkeypatch.setattr(m,'restart_panel',lambda:called.append(1));assert m.run_once()==0;assert called==[];assert state.read_text()=='1'


def test_panel_marked_overload_is_alive_but_an_unmarked_503_is_not(monkeypatch):
 m=load()
 marked=urllib.error.HTTPError(m.LIVE_URL,503,'busy',{},io.BytesIO(b'{"ok":false,"service":"comfy-panel","overloaded":true}'))
 monkeypatch.setattr(m.urllib.request,'urlopen',lambda *a,**k:(_ for _ in ()).throw(marked))
 assert m.probe_live() is True
 unmarked=urllib.error.HTTPError(m.LIVE_URL,503,'busy',{},io.BytesIO(b''))
 monkeypatch.setattr(m.urllib.request,'urlopen',lambda *a,**k:(_ for _ in ()).throw(unmarked))
 assert m.probe_live() is False
