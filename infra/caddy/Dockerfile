# TC-03-002: caddy:2 ships as root. This image adds uid 10001 so compose can
# run the proxy non-root. /data and /config are chowned here; a fresh named
# volume copies that ownership, so certificate storage survives a restart
# without baking any secret into the image.
FROM caddy:2
# The upstream binary has cap_net_bind_service as a file capability. A process
# whose bounding set dropped that capability cannot exec the file (EPERM).
# Compose grants NET_BIND_SERVICE only where low ports are required.
RUN addgroup -g 10001 -S caddy \
    && adduser -u 10001 -G caddy -S -H -h /tmp -s /sbin/nologin caddy \
    && setcap -r /usr/bin/caddy \
    && mkdir -p /data /config \
    && chown -R caddy:caddy /data /config
USER caddy
