# Shared helpers for the aware-server deploy scripts.
# Expects APP_DIR, VENV, RUN_USER, DEPLOY_USER, SERVICES, DOMAIN, SSL_CERT,
# SSL_KEY, SSL_CHAIN and INSTALL_CONFIGS to already be set by the caller.

# System packages the service depends on. Installing an already present
# package is a no-op, so rerunning brings in anything added here. Upgrading
# packages is left to the operating system's own update mechanism.
SYSTEM_PACKAGES="python3 python3-venv nginx-extras acl"

install_packages() {
    echo "==> Installing system packages"
    sudo apt-get update
    # shellcheck disable=SC2086
    sudo apt-get install -y $SYSTEM_PACKAGES
}

# Creates the dedicated service account the unit runs as, if it doesn't
# already exist. Refuses to proceed if RUN_USER is the deploying account, so
# the service can never end up running as whoever happens to deploy.
ensure_run_user() {
    if [ "$RUN_USER" = "$DEPLOY_USER" ]; then
        echo "RUN_USER is '$RUN_USER', the same as the deploying account ($DEPLOY_USER). The service must run as a dedicated, unprivileged user; set RUN_USER to something else (default: aware)." >&2
        exit 1
    fi
    if id -u "$RUN_USER" >/dev/null 2>&1; then
        return
    fi
    echo "==> Creating service user $RUN_USER"
    sudo adduser --system --group --no-create-home --shell /usr/sbin/nologin "$RUN_USER"
}

# Gives RUN_USER read access to the checkout and venv via ACLs (so git and the
# deployer's own permissions are left untouched), and nothing more. Idempotent;
# uses sudo.
install_permissions() {
    echo "==> Setting up service user permissions"
    local dir

    # Home directories are typically 0750, so the service user needs execute
    # (traverse) permission on every parent directory up to the checkout.
    dir="$(dirname "$APP_DIR")"
    while [ "$dir" != "/" ]; do
        sudo setfacl -m "u:$RUN_USER:x" "$dir"
        dir="$(dirname "$dir")"
    done

    # Read-only ACLs on the checkout and venv, with a default ACL so files
    # created later by git pull and pip install stay readable. No write bit.
    sudo setfacl -R -m "u:$RUN_USER:rX" -m "d:u:$RUN_USER:rX" "$APP_DIR"
    case "$VENV" in
        "$APP_DIR"/*) ;;
        *) sudo setfacl -R -m "u:$RUN_USER:rX" -m "d:u:$RUN_USER:rX" "$VENV" ;;
    esac

    # .env: readable to the service, writable only by the deployer.
    sudo chown "$DEPLOY_USER:$RUN_USER" "$APP_DIR/.env"
    sudo chmod 640 "$APP_DIR/.env"
}

# Compares a rendered config against the installed one; applies it when
# INSTALL_CONFIGS=yes, otherwise reports the diff. Returns 0 if it changed.
_apply_or_report() {
    local src="$1" target="$2" desc="$3"
    if [ -f "$target" ] && diff -q "$src" "$target" >/dev/null 2>&1; then
        echo "$desc: config up to date"
        return 1
    fi
    if [ "$INSTALL_CONFIGS" = "yes" ]; then
        sudo install -m 0644 "$src" "$target"
        echo "$desc: installed"
        return 0
    fi
    echo "Warning: $desc differs from the installed config at $target (or is not installed there)." >&2
    diff -u "$target" "$src" 2>&1 >&2 || true
    echo "Set INSTALL_CONFIGS=yes to apply this change." >&2
    return 1
}

render_services() {
    echo "==> Rendering systemd unit files"
    local changed=0
    local unit name tmp
    for unit in "$APP_DIR"/deploy/*.service; do
        name="$(basename "$unit")"
        tmp="$(mktemp)"
        sed -e "s|@RUN_USER@|$RUN_USER|g" -e "s|@APP_DIR@|$APP_DIR|g" "$unit" > "$tmp"
        if _apply_or_report "$tmp" "/etc/systemd/system/$name" "$name"; then
            changed=1
        fi
        rm -f "$tmp"
    done
    if [ "$changed" -eq 1 ]; then
        sudo systemctl daemon-reload
    fi
}

verify_services_active() {
    echo "==> Verifying services are active"
    local failed=()
    for service in $SERVICES; do
        if ! systemctl is-active --quiet "$service"; then
            failed+=("$service")
        fi
    done
    if [ "${#failed[@]}" -ne 0 ]; then
        echo "The following services are not active: ${failed[*]}" >&2
        exit 1
    fi
}

# Certificates normally live under /etc/letsencrypt, which is readable only by
# root, so check with sudo.
_cert_present() {
    sudo test -f "$1"
}

install_nginx() {
    echo "==> Rendering nginx configuration"
    local name tmp_site changed=0

    for name in DOMAIN SSL_CERT SSL_KEY SSL_CHAIN; do
        if [ -z "${!name}" ]; then
            echo "$name is not set in .env; cannot render the nginx config." >&2
            exit 1
        fi
    done

    # nginx refuses to load a config whose certificate or chain is missing.
    for path in "$SSL_CERT" "$SSL_KEY" "$SSL_CHAIN"; do
        if ! _cert_present "$path"; then
            echo "TLS file for $DOMAIN is missing at $path. Provision the certificate (e.g. via certbot) and rerun." >&2
            exit 1
        fi
    done

    tmp_site="$(mktemp)"
    sed -e "s|@DOMAIN@|$DOMAIN|g" -e "s|@SSL_CERT@|$SSL_CERT|g" -e "s|@SSL_KEY@|$SSL_KEY|g" \
        -e "s|@SSL_CHAIN@|$SSL_CHAIN|g" "$APP_DIR/deploy/nginx-site.conf" > "$tmp_site"

    if _apply_or_report "$tmp_site" /etc/nginx/sites-available/aware-server "nginx site config"; then
        changed=1
    fi
    rm -f "$tmp_site"

    if [ "$INSTALL_CONFIGS" = "yes" ]; then
        sudo ln -sf /etc/nginx/sites-available/aware-server /etc/nginx/sites-enabled/aware-server
    fi

    if [ "$changed" -eq 1 ]; then
        sudo nginx -t
        sudo systemctl reload nginx
    fi
}
