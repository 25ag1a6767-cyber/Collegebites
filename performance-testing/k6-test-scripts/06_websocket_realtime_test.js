import ws from "k6/ws";
import http from "k6/http";
import { check, sleep } from "k6";

/**
 * CollegeBites — Real-Time WebSocket & SSE Token Board Concurrency Test (Section 5D)
 * Tests concurrent WebSocket connections to /api/v1/ws/board/all (ping/pong & broadcast)
 * and one-shot SSE stream snapshots from /api/v1/realtime/board/stream?once=true.
 */

const BASE_URL = __ENV.BASE_URL || "http://127.0.0.1:8010";
const WS_BASE_URL = BASE_URL.replace(/^http/, "ws");

export const options = {
  vus: parseInt(__ENV.TARGET_VUS || "25", 10),
  duration: __ENV.DURATION || "10s",
};

export default function () {
  const sseRes = http.get(`${BASE_URL}/api/v1/realtime/board/stream?once=true&max_seconds=2`, {
    timeout: "10s",
  });
  check(sseRes, {
    "SSE stream status 200": (r) => r.status === 200,
    "SSE includes board.snapshot": (r) => r.body && r.body.includes("board.snapshot"),
  });

  const wsUrl = `${WS_BASE_URL}/api/v1/ws/board/all`;
  const res = ws.connect(wsUrl, {}, function (socket) {
    socket.on("open", function () {
      socket.send("ping");
    });
    socket.on("message", function (msg) {
      if (msg.includes("pong")) {
        socket.close();
      }
    });
    socket.setTimeout(function () {
      socket.close();
    }, 2000);
  });

  check(res, { "WebSocket handshake 101": (r) => r && r.status === 101 });
  sleep(0.2);
}
