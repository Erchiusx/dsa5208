FROM cassandra:5.0@sha256:ee178b38a2746a8e15a115bd038ad1f864391d04a84162a018cb0dd79511709a
USER root
RUN apt-get update && apt-get install -y --no-install-recommends iptables \
    && rm -rf /var/lib/apt/lists/* \
    && sed -ri 's/^read_request_timeout:.*/read_request_timeout: 1500ms/; s/^write_request_timeout:.*/write_request_timeout: 1500ms/; s/^range_request_timeout:.*/range_request_timeout: 3000ms/' /etc/cassandra/cassandra.yaml
