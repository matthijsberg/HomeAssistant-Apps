#!/usr/bin/env node24
/**
 * Minimal UCP4 Supervisor shim for UniFi OS Server running inside HAOS.
 * Connects to unifi-core's /api/ws/supervisor endpoint using the IPC bearer token
 * so setup checks (hasLegacyNet, getPorts, getResources) succeed cleanly.
 */

import { createRequire } from 'module';
import os from 'os';
import { statfsSync } from 'fs';

const require = createRequire('/usr/share/unifi-core/app/package.json');
const WebSocket = require('ws');
const UCPConnection = require('@ubnt/ucp4');

const TOKEN_URL = 'http://127.0.0.1:11081/api/supervisor/token';
const WS_URL = 'wss://127.0.0.1:11084/api/ws/supervisor';

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
