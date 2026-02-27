# /deploy — Safe Deployment with Backup and Verification

## When to use
When the user says "deploy", "push to prod", "ship it", or wants to deploy to a server.

## Steps
1. **PRE-FLIGHT CHECKS**:
   - search_knowledge("deploy issues production") for known deployment problems
   - Run full test suite — Gate 3 enforces this but do it explicitly
   - Check git status — ensure working tree is clean
   - Verify the target environment is reachable
2. **BACKUP** (if deploying to server):
   - SSH to server and create a timestamped backup of current deployment
   - Example: `ssh server 'cp -r /opt/app /opt/app.backup.$(date +%Y%m%d_%H%M%S)'`
   - Save backup location to memory
3. **DEPLOY**:
   - Use the project's standard deployment method
   - For direct deploys: scp/rsync files to server
   - For container deploys: docker push + pull
   - For git deploys: git push to deployment remote
4. **VERIFY**:
   - Health check the deployed service
   - Check logs for errors: `journalctl -u service -n 50`
   - Run a smoke test (curl endpoint, check response)
5. **ROLLBACK PLAN**:
   - If verification fails, restore from backup immediately
   - Save the failure details to memory
6. **POST-DEPLOY**:
   - remember_this() with deployment details, version, and timestamp
   - Update LIVE_STATE.json with deployment info
   - Update LIVE_STATE.json
