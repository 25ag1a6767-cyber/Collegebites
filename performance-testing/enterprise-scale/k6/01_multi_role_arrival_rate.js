import { runMultiRoleSession } from './common_flows.js';

const BASE_URLS = (__ENV.BASE_URLS || __ENV.BASE_URL || 'http://127.0.0.1:8011')
  .split(',')
  .map((u) => u.trim())
  .filter(Boolean);
const SEED_FILE = __ENV.SEED_FILE || './seed_context.json';
const RATE_PER_MIN = parseInt(__ENV.RATE_PER_MIN || '500', 10);
const DURATION = __ENV.DURATION || '40s';
const PRE_VUS = parseInt(__ENV.PRE_VUS || String(Math.min(180, Math.max(20, Math.ceil(RATE_PER_MIN / 8)))), 10);
const MAX_VUS = parseInt(__ENV.MAX_VUS || String(Math.min(400, Math.max(60, Math.ceil(RATE_PER_MIN / 3)))), 10);
const RUN_ID = __ENV.RUN_ID || `arr_${RATE_PER_MIN}`;
const WRITE_MODE = __ENV.WRITE_MODE || 'normal';

const ctx = JSON.parse(open(SEED_FILE));

export const options = {
  scenarios: {
    unique_user_sessions_per_minute: {
      executor: 'constant-arrival-rate',
      rate: RATE_PER_MIN,
      timeUnit: '1m',
      duration: DURATION,
      preAllocatedVUs: PRE_VUS,
      maxVUs: MAX_VUS,
      gracefulStop: '10s',
    },
  },
  thresholds: {
    read_api_duration: ['p(95)<500'],
    http_req_failed: ['rate<0.01'],
  },
  summaryTrendStats: ['avg', 'min', 'med', 'p(90)', 'p(95)', 'p(99)', 'max'],
};

export default function () {
  const baseUrl = BASE_URLS[(__VU + __ITER) % BASE_URLS.length];
  runMultiRoleSession(ctx, baseUrl, RUN_ID, __VU, __ITER, WRITE_MODE);
}
