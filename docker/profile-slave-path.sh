# shellcheck shell=sh
# Installed as /etc/profile.d/slave.sh. Debian's /etc/profile resets PATH for
# every login shell (`bash -l`, `docker exec <c> bash -l`, ssh, the terminal
# tool's background `bash -lic`), dropping the image's ENV PATH dirs, so bare
# `slave` exits 127 there. Put them back in the ENV PATH order; dirs a login
# PATH already lists keep their position.
for __slave_p in /opt/data/.local/bin /opt/hermes/.venv/bin /opt/hermes/bin; do
    case ":$PATH:" in
        *":$__slave_p:"*) ;;
        *) PATH="$__slave_p:$PATH" ;;
    esac
done
unset __slave_p
export PATH
