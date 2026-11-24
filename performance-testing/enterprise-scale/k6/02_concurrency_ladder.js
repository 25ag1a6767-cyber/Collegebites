import { sleep } from 'k6';
import { runMultiRoleSession } from './common_flows.js';

const BASE_URLS = (__ENV.BASE_URLS || __ENV.BASE_URL || 'http://127.0.0.1:8011')
  .split(',')
  .map((u) => u.trim())
  .filter(Boolean);
const SEED_FILE = __ENV.SEED_FILE || './seed_context.json';
const TARGET_VUS = parseInt(__ENV.TARGET_VUS || '50', 10);
const DURATION = __ENV.DURATION || '25s';
const THINK_SECONDS = parseFloat(__ENV.THINK_SECONDS || '0.6');
const RUN_ID = __ENV.RUN_ID || `vu_${TARGET_VUS}`;
const WRITE_MODE = __ENV.WRITE_MODE || 'normal';

const ctx = JSON.parse(open(SEED_FILE));

export const options = {
  scenarios: {
    concurrent_users: {
      executor: 'constant-vus',
      vus: TARGET_VUS,
      duration: DURATION,
      gracefulStop: '10s',
    },
  },
  summaryTrendStats: ['avg', 'min', 'med', 'p(90)', 'p(95)', 'p(99)', 'max'],
};

export default function () {
  const baseUrl = BASE_URLS[(__VU + __ITER) % BASE_URLS.length];
  runMultiRoleSession(ctx, baseUrl, RUN_ID, __VU, __ITER, WRITE_MODE, 'concurrent');
  if (THINK_SECONDS > 0) {
    sleep(THINK_SECONDS);
  }
}
