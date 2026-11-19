#!/bin/bash
# Healthcheck + idempotent replica-set initialisation.
# Healthy only when this node is a writable PRIMARY of replica set "rs0".
# The member host is "database" (the compose service name) so the backend
# container can reach the primary through Docker networking.

RS_HOST="${RS_HOST:-database:27017}"

mongosh --quiet --port 27017 --eval "
const h = db.hello();
if (h.isWritablePrimary && h.setName === 'rs0') { quit(0); }
if (!h.setName) {
  // Not initiated yet (fresh volume) -> initiate. Failures are ignored; the next check retries.
  try { rs.initiate({ _id: 'rs0', members: [{ _id: 0, host: '${RS_HOST}' }] }); } catch (e) {}
}
quit(1);
"
