import { runMultiRoleSession } from './common_flows.js';

const BASE_URLS = (__ENV.BASE_URLS || __ENV.BASE_URL || 'http://127.0.0.1:8011')
  .split(',')
  .map((u) => u.trim())
  .filter(Boolean);
const SEED_FILE = __ENV.SEED_FILE || './seed_context.json';
const RATE_PER_MIN = parseInt(__ENV.RATE_PER_MIN || '1000', 10);
const DURATION = __ENV.DURATION || '120s';
const RUN_ID = __ENV.RUN_ID || 'endurance_soak';
const WRITE_MODE = __ENV.WRITE_MODE || 'normal';

const ctx = JSON.parse(open(SEED_FILE));

export const options = {
  scenarios: {
    sustained_endurance_soak: {
      executor: 'constant-arrival-rate',
      rate: RATE_PER_MIN,
      timeUnit: '1m',
      duration: DURATION,
      preAllocatedVUs: 120,
      maxVUs: 350,
      gracefulStop: '10s',
    },
  },
  summaryTrendStats: ['avg', 'min', 'med', 'p(90)', 'p(95)', 'p(99)', 'max'],
};

export default function () {
  const baseUrl = BASE_URLS[(__VU + __ITER) % BASE_URLS.length];
  runMultiRoleSession(ctx, baseUrl, RUN_ID, __VU, __ITER, WRITE_MODE);
}
