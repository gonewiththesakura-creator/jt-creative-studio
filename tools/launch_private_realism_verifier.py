"""Launch the resumable verifier on the relay without exposing its API key."""
import base64, importlib.util, json, pathlib, paramiko, shlex, sys

BASE = pathlib.Path(r"D:/LAN-Share/lora/_work/comfy_panel")
SOURCE = pathlib.Path(r"D:/LAN-Share/lora/_work/prepared/style3_style/holdout/3_102.png")
REMOTE_SCRIPT = "/tmp/verify_private_realism_runninghub.py"
ORDER = [
    "realism_2511", "realism_multisample", "realism_qwen_zi",
    "realism_4k_text", "realism_3in1", "realism_zi_flowmatch",
]

spec = importlib.util.spec_from_file_location("private_realism_launcher_server", BASE / "server.py")
server = importlib.util.module_from_spec(spec); spec.loader.exec_module(server)
payloads = []
for internal_id in ORDER:
    workflow = server.WORKFLOWS[internal_id]
    media = {key: "__UPLOADED__" for key in workflow.get("rh_media", {})}
    trusted_media, trusted_params = server.normalize_rh_workflow_inputs(workflow, media, {})
    nodes = server.rh_build_generic_node_info({"media": trusted_media, "params": trusted_params}, workflow)
    payloads.append({"internal_id": internal_id, "workflow_id": workflow["rh_workflow_id"],
                     "instance_type": workflow.get("rh_instance_type", "default"), "nodes": nodes})

creds = json.loads((BASE / "tools" / "creds.json").read_text(encoding="utf-8"))
client = paramiko.SSHClient(); client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
client.connect(creds["host"], port=int(creds["port"]), username=creds["user"], password=creds["password"], timeout=30, allow_agent=False, look_for_keys=False)
sftp = client.open_sftp(); sftp.put(str(SOURCE), "/tmp/private_realism_input.png"); sftp.put(str(BASE / "tools" / "verify_private_realism_runninghub.py"), REMOTE_SCRIPT); sftp.close()
payload_b64 = base64.b64encode(json.dumps(payloads, ensure_ascii=False).encode()).decode()
command = (
    "set -a; . /home/admin/comfy-panel/panel.env; set +a; "
    f"export PRIVATE_REALISM_PAYLOADS=$(printf %s {shlex.quote(payload_b64)} | base64 -d); "
    f"python3 {shlex.quote(REMOTE_SCRIPT)}"
)
_, stdout, stderr = client.exec_command(command, timeout=15000)
for line in iter(stdout.readline, ""):
    print(line, end="", flush=True)
error = stderr.read().decode("utf-8", "replace")
if error: print("STDERR", error[:2000], file=sys.stderr)
code = stdout.channel.recv_exit_status(); client.close(); raise SystemExit(code)
