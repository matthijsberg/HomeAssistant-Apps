#!/usr/bin/env node24
/**
 * Minimal UCP4 Supervisor shim for UniFi OS Server running inside HAOS.
 * Connects to unifi-core's /api/ws/supervisor endpoint using the IPC bearer token
 * so setup checks (hasLegacyNet, getPorts, getResources) succeed cleanly, and
 * syncs the Home Assistant /ssl certificate into unifi-core's userCertificates API.
 */

import { createRequire } from 'module';
import { createPrivateKey, X509Certificate } from 'crypto';
import { chmodSync, existsSync, readdirSync, readFileSync, statfsSync } from 'fs';
import os from 'os';
import path from 'path';

const require = createRequire('/usr/share/unifi-core/app/package.json');
const WebSocket = require('ws');
const UCPConnection = require('@ubnt/ucp4');

const IPC_BASE = 'http://127.0.0.1:11081';
const TOKEN_URL = `${IPC_BASE}/api/supervisor/token`;
const WS_URL = 'wss://127.0.0.1:11084/api/ws/supervisor';
const OPTIONS_PATH = '/data/options.json';
const HA_CERT_NAME = 'ha-ssl';

function getResourcesPayload() {
  const cpus = Math.max(1, os.cpus().length);
  const ramMb = Math.max(1024, Math.round(os.totalmem() / (1024 * 1024)));
  let storageGb = 32;
  try {
    const st = statfsSync('/data');
    storageGb = Math.max(8, Math.round((Number(st.blocks) * Number(st.bsize)) / (1024 ** 3)));
  } catch {
    // fallback default
  }
  return {
    cpus: { min: 1, max: cpus, current: cpus },
    ramMb: { min: 1024, max: ramMb, current: ramMb },
    storageGb: { min: 8, max: storageGb, current: storageGb },
  };
}

function readAddonOptions() {
  const defaults = {
    use_ha_ssl: true,
    ssl_cert: 'fullchain.pem',
    ssl_key: 'privkey.pem',
  };
  try {
    if (!existsSync(OPTIONS_PATH)) return defaults;
    const raw = JSON.parse(readFileSync(OPTIONS_PATH, 'utf8'));
    return {
      use_ha_ssl: raw.use_ha_ssl !== undefined ? Boolean(raw.use_ha_ssl) : true,
      ssl_cert: raw.ssl_cert || 'fullchain.pem',
      ssl_key: raw.ssl_key || 'privkey.pem',
    };
  } catch {
    return defaults;
  }
}

function resolveSslPath(filename) {
  const resolved = path.resolve('/ssl', String(filename || ''));
  return resolved.startsWith('/ssl/') ? resolved : null;
}

function loadValidHaCertPair(opts) {
  if (!opts.use_ha_ssl || !existsSync('/ssl')) return null;

  const customCrt = resolveSslPath(opts.ssl_cert);
  const customKey = resolveSslPath(opts.ssl_key);
  const candidates = [
    ...(customCrt && customKey ? [[customCrt, customKey]] : []),
    ['/ssl/fullchain.pem', '/ssl/privkey.pem'],
  ];

  for (const [crtPath, keyPath] of candidates) {
    if (!existsSync(crtPath) || !existsSync(keyPath)) continue;
    try {
      const cert = readFileSync(crtPath, 'utf8');
      const key = readFileSync(keyPath, 'utf8');
      const x509 = new X509Certificate(cert);
      const priv = createPrivateKey(key);
      if (!x509.checkPrivateKey(priv)) {
        console.warn(`[uos-supervisor-shim] SSL key mismatch for ${crtPath}`);
        continue;
      }
      if (Date.now() > new Date(x509.validTo).getTime()) {
        console.warn(`[uos-supervisor-shim] SSL certificate expired at ${crtPath}`);
        continue;
      }
      return { cert, key, fingerprint: x509.fingerprint, crtPath };
    } catch (err) {
      console.warn(`[uos-supervisor-shim] Invalid SSL pair at ${crtPath}:`, err.message);
    }
  }
  return null;
}

async function ipcJson(urlPath, method = 'GET', body = null) {
  const init = {
    method,
    signal: AbortSignal.timeout(10000),
    headers: {},
  };
  if (body !== null) {
    init.headers['Content-Type'] = 'application/json';
    init.body = JSON.stringify(body);
  }
  const res = await fetch(`${IPC_BASE}${urlPath}`, init);
  const text = await res.text();
  if (!res.ok) {
    throw new Error(`${method} ${urlPath} -> HTTP ${res.status}: ${text}`);
  }
  return text ? JSON.parse(text) : null;
}

function hardenTlsKeyPermissions() {
  const dirs = ['/data/uos_storage/unifi-core/config', '/data/unifi-core/config'];
  for (const dir of dirs) {
    if (!existsSync(dir)) continue;
    try {
      for (const entry of readdirSync(dir)) {
        if (entry.endsWith('.key')) {
          chmodSync(path.join(dir, entry), 0o600);
        }
      }
    } catch (err) {
      console.warn(`[uos-supervisor-shim] Could not harden TLS key permissions in ${dir}:`, err.message);
    }
  }
}

async function syncHaSslCertificate() {
  try {
    const opts = readAddonOptions();
    const existing = (await ipcJson('/api/userCertificates')) || [];
    const haCerts = existing.filter((c) => c.name === HA_CERT_NAME);
    const pair = loadValidHaCertPair(opts);

    if (!pair) {
      for (const c of haCerts) {
        if (c.active) {
          await ipcJson(`/api/userCertificates/${c.id}/status`, 'PUT', { active: false });
          console.log('[uos-supervisor-shim] Deactivated custom HA SSL certificate; using built-in self-signed cert');
        }
      }
      return;
    }

    const matching = haCerts.find((c) => c.fingerprint === pair.fingerprint);
    if (matching) {
      if (!matching.active) {
        await ipcJson(`/api/userCertificates/${matching.id}/status`, 'PUT', { active: true });
        console.log(`[uos-supervisor-shim] Activated HA SSL certificate (${pair.crtPath})`);
      }
      return;
    }

    for (const old of haCerts) {
      if (old.active) {
        await ipcJson(`/api/userCertificates/${old.id}/status`, 'PUT', { active: false });
      }
      await ipcJson(`/api/userCertificates/${old.id}`, 'DELETE');
    }

    const created = await ipcJson('/api/userCertificates', 'POST', {
      name: HA_CERT_NAME,
      cert: pair.cert,
      key: pair.key,
    });
    await ipcJson(`/api/userCertificates/${created.id}/status`, 'PUT', { active: true });
    console.log(`[uos-supervisor-shim] Deployed and activated HA SSL certificate (${pair.crtPath})`);
  } catch (err) {
    console.error('[uos-supervisor-shim] SSL sync warning:', err.message);
  } finally {
    hardenTlsKeyPermissions();
  }
}

async function fetchSupervisorToken() {
  const res = await fetch(TOKEN_URL, { signal: AbortSignal.timeout(3000) });
  if (!res.ok) {
    throw new Error(`Token HTTP ${res.status}`);
  }
  return (await res.text()).trim();
}

async function connectOnce() {
  const token = await fetchSupervisorToken();
  if (!token) throw new Error('Empty supervisor token');

  await new Promise((resolve) => {
    const ws = new WebSocket(WS_URL, {
      headers: { Authorization: `Bearer ${token}` },
      rejectUnauthorized: false,
    });

    const ucp = new UCPConnection(ws, { requestTimeout: 30000 });

    ucp.on('open', () => {
      console.log('[uos-supervisor-shim] Connected to /api/ws/supervisor');
      setTimeout(() => {
        syncHaSslCertificate();
      }, 1500);
    });

    ucp.on('event', () => {
      // Accept systemState, runnableStateChanged, setupCompleted events silently
    });

    ucp.on('request', async (req) => {
      try {
        switch (req.action) {
          case 'hasLegacyNet':
            await req.respond({ hasLegacyNet: false });
            break;
          case 'legacyNetBackup':
            await req.respond({ backupCreated: false });
            break;
          case 'getPorts':
            await req.respond({ webPort: 11443 });
            break;
          case 'getResources':
            await req.respond(getResourcesPayload());
            break;
          case 'firmwareUpdateToken':
          case 'firmwareReleaseChannel':
          case 'setPorts':
          case 'setResources':
          case 'exportSupportData':
          case 'firmwareUpdate':
          case 'resetToDefaults':
          case 'restart':
          case 'poweroff':
            await req.respond({});
            break;
          default:
            await req.respond({});
            break;
        }
      } catch (err) {
        console.error(`[uos-supervisor-shim] Error handling ${req.action}:`, err);
      }
    });

    ucp.on('error', (err) => {
      console.error('[uos-supervisor-shim] UCP error:', err.message);
    });

    ucp.on('connectionerror', (err) => {
      console.error('[uos-supervisor-shim] WS error:', err.message);
    });

    ucp.on('close', () => {
      console.log('[uos-supervisor-shim] Connection closed, will retry');
      resolve();
    });
  });
}

async function main() {
  while (true) {
    try {
      await connectOnce();
    } catch {
      // unifi-core may still be starting; retry silently
    }
    await new Promise((r) => setTimeout(r, 2000));
  }
}

main();
