import http from 'k6/http';
import crypto from 'k6/crypto';
import { check } from 'k6';
import { Counter, Rate, Trend } from 'k6/metrics';

export const readApiDuration = new Trend('read_api_duration', true);
export const writeTxnDuration = new Trend('write_txn_duration', true);
export const authLoginDuration = new Trend('auth_login_duration', true);

export const readApiFailed = new Rate('read_api_failed');
export const writeTxnFailed = new Rate('write_txn_failed');

export const http4xxErrors = new Counter('http_4xx_errors');
export const http5xxErrors = new Counter('http_5xx_errors');
export const http429Errors = new Counter('http_429_errors');
export const timeoutErrors = new Counter('timeout_errors');
export const ordersCreated = new Counter('orders_created');
export const paymentsVerified = new Counter('payments_verified');
export const sessionsCompleted = new Counter('sessions_completed');

const RZP_TEST_SECRET = __ENV.RZP_TEST_SECRET || 'rzp_test_secret_collegebites_local';

export function buildFakeIp(seedNum) {
  const n = Math.abs(seedNum) + 1;
  const o2 = (Math.floor(n / 65025) % 250) + 1;
  const o3 = (Math.floor(n / 255) % 250) + 1;
  const o4 = (n % 250) + 1;
  return `10.${o2}.${o3}.${o4}`;
}

function recordResponse(res, kind) {
  if (!res || res.status === 0) {
    timeoutErrors.add(1);
    if (kind === 'read') readApiFailed.add(1);
    if (kind === 'write') writeTxnFailed.add(1);
    return false;
  }
  const ok = res.status >= 200 && res.status < 300;
  if (res.status === 429) {
    http429Errors.add(1);
    http4xxErrors.add(1);
  } else if (res.status >= 400 && res.status < 500) {
    http4xxErrors.add(1);
  } else if (res.status >= 500) {
    http5xxErrors.add(1);
  }

  if (kind === 'read') {
    readApiDuration.add(res.timings.duration);
    readApiFailed.add(ok ? 0 : 1);
  } else if (kind === 'write') {
    writeTxnDuration.add(res.timings.duration);
    writeTxnFailed.add(ok ? 0 : 1);
  } else if (kind === 'auth') {
    authLoginDuration.add(res.timings.duration);
    writeTxnFailed.add(ok ? 0 : 1);
  }
  return ok;
}

function getJson(url, headers, tag, kind = 'read') {
  const res = http.get(url, {
    headers,
    timeout: '15s',
    tags: { endpoint: tag, kind },
  });
  recordResponse(res, kind);
  return res;
}

function postJson(url, bodyObj, headers, tag, kind = 'write') {
  const res = http.post(url, JSON.stringify(bodyObj), {
    headers: Object.assign({ 'Content-Type': 'application/json' }, headers),
    timeout: '20s',
    tags: { endpoint: tag, kind },
  });
  recordResponse(res, kind);
  return res;
}

function patchJson(url, bodyObj, headers, tag, kind = 'write') {
  const res = http.patch(url, JSON.stringify(bodyObj), {
    headers: Object.assign({ 'Content-Type': 'application/json' }, headers),
    timeout: '20s',
    tags: { endpoint: tag, kind },
  });
  recordResponse(res, kind);
  return res;
}

export function runMultiRoleSession(ctx, baseUrl, runId, vu, iter, writeMode = 'normal', sessionMode = 'arrival') {
  const bucket = (vu * 31 + iter) % 100;
  const fakeIp = buildFakeIp(vu * 10007 + iter);
  const cid = ctx.canteen_id;

  // 65% Student sessions
  if (bucket < 65) {
    const stuIdx = (vu + iter) % ctx.students.length;
    const stu = ctx.students[stuIdx];
    let token = stu.token;

    // Arrival mode: 10% of arriving sessions perform a fresh Argon2id password login.
    // Concurrent VU mode: 15% of VUs perform a real login on first entry (iter===0), then reuse their JWT session realistically.
    const doFreshLogin =
      writeMode !== 'readonly' &&
      (sessionMode === 'concurrent' ? iter === 0 && (vu % 7 === 0) : ((vu + iter) % 10 === 0));
    if (doFreshLogin) {
      const loginRes = postJson(
        `${baseUrl}/api/v1/auth/login`,
        { identifier: stu.email, password: stu.password },
        { 'X-Forwarded-For': fakeIp },
        'POST /auth/login',
        'auth'
      );
      if (loginRes.status === 200) {
        try {
          const body = loginRes.json();
          if (body && body.access_token) token = body.access_token;
        } catch (_e) {}
      }
    }

    const stuHdr = {
      Authorization: `Bearer ${token}`,
      'X-Forwarded-For': fakeIp,
    };

    // Browse canteens, categories, menu items, and public token board
    const r1 = getJson(`${baseUrl}/api/v1/canteens`, stuHdr, 'GET /canteens', 'read');
    const r2 = getJson(`${baseUrl}/api/v1/menus/canteens/${cid}/categories`, stuHdr, 'GET /menus/categories', 'read');
    const r3 = getJson(`${baseUrl}/api/v1/menus/canteens/${cid}/items`, stuHdr, 'GET /menus/items', 'read');
    const r4 = getJson(`${baseUrl}/api/v1/pickup/board`, stuHdr, 'GET /pickup/board', 'read');

    check(r1, { 'student canteens 200': (r) => r.status === 200 });
    check(r3, { 'student menu items 200': (r) => r.status === 200 });
    check(r4, { 'student board 200': (r) => r.status === 200 });

    // Arrival mode: ~17% of student sessions place a real order + Razorpay HMAC verify.
    // Concurrent VU mode: ~8% of loop cycles place a real order (realistic browse-to-buy ratio while active).
    const orderMod = sessionMode === 'concurrent' ? 12 : 6;
    const doOrder = writeMode !== 'readonly' && ((vu * 7 + iter) % orderMod === 0);
    if (doOrder) {
      const foodId = ctx.order_food_ids[(vu + iter) % ctx.order_food_ids.length];
      const idemKey = `k6-${runId}-${vu}-${iter}`;
      const chkRes = postJson(
        `${baseUrl}/api/v1/orders/checkout`,
        {
          canteen_id: cid,
          order_type: 'pickup',
          order_channel: 'web',
          payment_method: 'razorpay',
          accepted_policy: true,
          use_cart: false,
          idempotency_key: idemKey,
          direct_items: [{ food_item_id: foodId, quantity: 1 }],
        },
        stuHdr,
        'POST /orders/checkout',
        'write'
      );
      if (chkRes.status === 201) {
        ordersCreated.add(1);
        try {
          const orderObj = chkRes.json();
          const rzpOrderId = orderObj.razorpay_order_id;
          const rzpPayId = `pay_k6_${runId}_${vu}_${iter}`;
          if (rzpOrderId) {
            const sig = crypto.hmac('sha256', RZP_TEST_SECRET, `${rzpOrderId}|${rzpPayId}`, 'hex');
            const verRes = postJson(
              `${baseUrl}/api/v1/payments/razorpay/verify`,
              {
                order_id: orderObj.id,
                razorpay_order_id: rzpOrderId,
                razorpay_payment_id: rzpPayId,
                razorpay_signature: sig,
                payment_method: 'upi',
              },
              stuHdr,
              'POST /payments/razorpay/verify',
              'write'
            );
            if (verRes.status === 200) {
              paymentsVerified.add(1);
            }
          }
        } catch (_e) {}
      }
      getJson(`${baseUrl}/api/v1/orders/my?limit=15`, stuHdr, 'GET /orders/my', 'read');
    } else if ((iter % 3) === 0) {
      getJson(`${baseUrl}/api/v1/orders/my?limit=15`, stuHdr, 'GET /orders/my', 'read');
    }

    sessionsCompleted.add(1);
    return;
  }

  // 15% Canteen Manager sessions
  if (bucket < 80) {
    const mgrIdx = (vu + iter) % ctx.managers.length;
    const mgrHdr = {
      Authorization: `Bearer ${ctx.managers[mgrIdx].token}`,
      'X-Forwarded-For': fakeIp,
    };

    const rk = getJson(`${baseUrl}/api/v1/kitchen/canteens/${cid}/orders`, mgrHdr, 'GET /kitchen/orders', 'read');
    const rq = getJson(`${baseUrl}/api/v1/queue/canteens/${cid}`, mgrHdr, 'GET /queue/canteen', 'read');
    const rb = getJson(`${baseUrl}/api/v1/pickup/token-board`, mgrHdr, 'GET /pickup/token-board', 'read');
    check(rq, { 'manager queue 200': (r) => r.status === 200 });
    check(rb, { 'manager token-board 200': (r) => r.status === 200 });

    // Occasional safe menu toggle write (tests live Redis cache invalidation under load)
    if (writeMode !== 'readonly' && ((vu + iter) % 8 === 0) && ctx.toggle_food_id) {
      patchJson(
        `${baseUrl}/api/v1/menus/items/${ctx.toggle_food_id}`,
        { is_featured: (iter % 2) === 0 },
        mgrHdr,
        'PATCH /menus/items',
        'write'
      );
    }

    sessionsCompleted.add(1);
    return;
  }

  // 10% Inventory Manager sessions
  if (bucket < 90) {
    const invIdx = (vu + iter) % ctx.inventory_managers.length;
    const invHdr = {
      Authorization: `Bearer ${ctx.inventory_managers[invIdx].token}`,
      'X-Forwarded-For': fakeIp,
    };

    const ri = getJson(`${baseUrl}/api/v1/inventory/canteens/${cid}/items`, invHdr, 'GET /inventory/items', 'read');
    const ra = getJson(`${baseUrl}/api/v1/inventory/canteens/${cid}/alerts`, invHdr, 'GET /inventory/alerts', 'read');
    const rs = getJson(`${baseUrl}/api/v1/inventory/suppliers`, invHdr, 'GET /inventory/suppliers', 'read');
    const rp = getJson(`${baseUrl}/api/v1/inventory/canteens/${cid}/purchase-orders`, invHdr, 'GET /inventory/purchase-orders', 'read');
    check(ri, { 'inventory items 200': (r) => r.status === 200 });
    check(ra, { 'inventory alerts 200': (r) => r.status === 200 });
    check(rs, { 'inventory suppliers 200': (r) => r.status === 200 });
    check(rp, { 'inventory POs 200': (r) => r.status === 200 });

    if (writeMode !== 'readonly' && ((vu + iter) % 10 === 0) && ctx.adjust_inventory_id) {
      const delta = (iter % 2 === 0) ? '1' : '-1';
      postJson(
        `${baseUrl}/api/v1/inventory/adjustments`,
        {
          inventory_item_id: ctx.adjust_inventory_id,
          quantity_delta: delta,
          reason: 'Staging load cycle stock reconciliation',
          operation_type: 'adjustment',
        },
        invHdr,
        'POST /inventory/adjustments',
        'write'
      );
    }

    sessionsCompleted.add(1);
    return;
  }

  // 10% Administrator sessions
  const admIdx = (vu + iter) % ctx.admins.length;
  const admHdr = {
    Authorization: `Bearer ${ctx.admins[admIdx].token}`,
    'X-Forwarded-For': fakeIp,
  };

  const rd = getJson(`${baseUrl}/api/v1/reports/dashboard?preset=last_30_days`, admHdr, 'GET /reports/dashboard', 'read');
  const ro = getJson(`${baseUrl}/api/v1/admin/orders?limit=50`, admHdr, 'GET /admin/orders', 'read');
  const rc = getJson(`${baseUrl}/api/v1/reports/operations-control-center`, admHdr, 'GET /reports/occ', 'read');
  const ru = getJson(`${baseUrl}/api/v1/admin/users`, admHdr, 'GET /admin/users', 'read');
  const rh = getJson(`${baseUrl}/api/v1/admin/health`, admHdr, 'GET /admin/health', 'read');

  check(rd, { 'admin dashboard 200': (r) => r.status === 200 });
  check(ro, { 'admin orders 200': (r) => r.status === 200 });
  check(rc, { 'admin occ 200': (r) => r.status === 200 });
  check(ru, { 'admin users 200': (r) => r.status === 200 });
  check(rh, { 'admin health 200': (r) => r.status === 200 });

  sessionsCompleted.add(1);
}
