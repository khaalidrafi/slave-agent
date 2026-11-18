"""The worker client's environment is an allowlist of host plumbing (``kanban_worker_env``)."""

from slave_cli.kanban_worker_env import worker_client_env


def test_keeps_host_plumbing_and_slave_location(tmp_path):
    env = {"PATH": "/bin", "HOME": "/home/u", "LC_ALL": "C.UTF-8", "HTTPS_PROXY": "http://p",
           "https_proxy": "http://p", "SLAVE_HOME": "/h", "XDG_RUNTIME_DIR": "/run/user/1",
           "XDG_STATE_HOME": "/s", "SLAVE_GATEWAY_LOCK_DIR": "/locks", "SLAVE_DISABLE_LAZY_INSTALLS": "1",
           "SSH_AUTH_SOCK": "/run/user/1/ssh-agent.sock", "DISPLAY": ":0", "WAYLAND_DISPLAY": "wayland-0",
           "XAUTHORITY": "/home/u/.Xauthority"}
    assert worker_client_env(env, tmp_path / "assignee") == env


def test_drops_everything_else(tmp_path):
    env = {"PATH": "/bin", "SERVICE_TOKEN": "t", "GITHUB_TOKEN": "g", "SLAVE_MODEL": "m",
           "TERMINAL_ENV": "docker", "SLAVE_TUI": "1", "SLAVE_SESSION_PLATFORM": "telegram",
           "MY_PASSTHROUGH_VAR": "v", "XDG_ACTIVATION_TOKEN": "a", "XDG_SERVICE_TOKEN": "x"}
    assert worker_client_env(env, tmp_path / "assignee") == {"PATH": "/bin"}


def test_keeps_the_instance_config_deployment_and_managed_dir(tmp_path, monkeypatch):
    """The config backend's deployment (which backend, plane and instance) and the managed-scope
    directory are the instance's, not a profile's: a gateway the client cold-starts for the assignee
    without them reads the assignee's config from the file backend, or loses the admin overlay."""
    monkeypatch.setenv("SLAVE_CONFIG_BACKEND", "remote")
    deployment = {"SLAVE_CONFIG_BACKEND": "remote", "SLAVE_CONFIG_REMOTE_URL": "https://plane.example",
                  "SLAVE_CONFIG_INSTANCE_ID": "inst-1", "SLAVE_MANAGED_DIR": str(tmp_path / "managed")}
    env = {"PATH": "/bin", **deployment, "SERVICE_TOKEN": "t"}
    assert worker_client_env(env, tmp_path / "assignee") == {"PATH": "/bin", **deployment}


def test_never_keeps_the_config_plane_credential(tmp_path, monkeypatch):
    """The deployment is kept, its credential is not: the assignee resolves its own and fails closed."""
    from plugins.config_backends.remote.credentials import PLANE_CREDENTIAL_ENV_NAMES

    monkeypatch.setenv("SLAVE_CONFIG_BACKEND", "remote")
    deployment = {"SLAVE_CONFIG_BACKEND", "SLAVE_CONFIG_REMOTE_URL", "SLAVE_CONFIG_INSTANCE_ID"}
    credentials = sorted(PLANE_CREDENTIAL_ENV_NAMES - deployment)
    assert credentials, "the remote backend names at least one credential"
    env = {"PATH": "/bin", "SLAVE_CONFIG_BACKEND": "remote", **{name: "secret" for name in credentials}}
    assert worker_client_env(env, tmp_path / "assignee") == {"PATH": "/bin", "SLAVE_CONFIG_BACKEND": "remote"}
