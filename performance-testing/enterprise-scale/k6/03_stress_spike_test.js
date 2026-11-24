import { runMultiRoleSession } from './common_flows.js';

const BASE_URLS = (__ENV.BASE_URLS || __ENV.BASE_URL || 'http://127.0.0.1:8011')
  .split(',')
  .map((u) => u.trim())
  .filter(Boolean);
const SEED_FILE = __ENV.SEED_FILE || './seed_context.json';
const RUN_ID = __ENV.RUN_ID || 'spike_stress';
const WRITE_MODE = __ENV.WRITE_MODE || 'normal';

const ctx = JSON.parse(open(SEED_FILE));

export const options = {
  scenarios: {
    lunch_rush_spike_and_recovery: {
      executor: 'ramping-arrival-rate',
      startRate: 100,
      timeUnit: '1m',
      preAllocatedVUs: 80,
      maxVUs: 350,
      stages: [
        { duration: '15s', target: 500 },   // Ramp up to minimum enterprise target
        { duration: '20s', target: 1000 },  // Primary 1,000 sessions/min target
        { duration: '20s', target: 1500 },  // Lunch-rush 150% burst spike
        { duration: '20s', target: 250 },   // Post-rush cooldown recovery check
      ],
      gracefulStop: '10s',
    },
  },
  summaryTrendStats: ['avg', 'min', 'med', 'p(90)', 'p(95)', 'p(99)', 'max'],
};

export default function () {
  const baseUrl = BASE_URLS[(__VU + __ITER) % BASE_URLS.length];
  runMultiRoleSession(ctx, baseUrl, RUN_ID, __VU, __ITER, WRITE_MODE);
}
