# Cinema Chat - Cleanup Log

**Date Started:** 2025-11-30
**Purpose:** Comprehensive codebase cleanup for developer handoff

## Cleanup Objectives

1. Remove all references to old project names (Sphinx, The Turning Point, Hume)
2. Delete temporary, cache, and development artifact files
3. Ensure all code is well-documented with inline comments
4. Verify no redundant code exists
5. Organize and consolidate documentation
6. Create comprehensive handoff documentation

## File-by-File Progress

### Phase 1: Git Commit & Immediate Cleanup

#### Task 1: Commit Current Changes ✅
- [ ] Review current modified files
- [ ] Create commit with descriptive message
- [ ] Verify commit authorship

#### Task 2: Fix Merge Conflicts ⏳
- [ ] `cinema-bot-app/.gitignore` - Lines 47-52 have merge conflict markers

#### Task 3: Remove Temporary/Cache Files ⏳
- [ ] Delete `.gitignore-temp`
- [ ] Delete `cinema-bot-app/backend/src/cinema-bot/__pycache__/` (11 files)
- [ ] Delete `mcp/__pycache__/` (2 files)

#### Task 4: Delete Old/Broken Frontend Pages ⏳
- [ ] Delete `cinema-bot-app/frontend-next/pages/index_old.tsx`
- [ ] Delete `cinema-bot-app/frontend-next/pages/index_broken.tsx`
- [ ] Delete `cinema-bot-app/frontend-next/pages/index_simple.tsx`
- [ ] Delete `cinema-bot-app/frontend-next/pages/index_old_rtvi_client.tsx`

---

### Phase 2: Old Project Name Cleanup (CRITICAL)

#### Task 5: Frontend README Update ⏳
**File:** `cinema-bot-app/frontend-next/README.md`
- [ ] Line 1: Replace "Sphinx Voice Bot" with "Cinema Chat"
- [ ] Lines 3, 9, 35, 62, 68, 71, 81, 98, 103, 126, 181: Replace all Sphinx references
- [ ] Lines 9, 62, 118: Update Hume AI references (document removal)
- [ ] Review entire document for accuracy

#### Task 6: Logo/Favicon Files ⏳
- [ ] Rename `cinema-bot-app/frontend-next/public/sphinx.svg` to `cinema-chat.svg` or remove
- [ ] Update `cinema-bot-app/scripts/generate-favicon.js` line 7 to reference correct SVG
- [ ] Generate new favicon if needed

#### Task 7: Architecture Diagram ⏳
**File:** `cinema-bot-app/architecture-diagram.html`
- [ ] Line 6: Change title from "Turning Point Voice Bot" to "Cinema Chat"
- [ ] Line 120: Remove or update Hume AI reference in diagram
- [ ] Review entire diagram for accuracy

#### Task 8: API Route Cleanup ⏳
**File:** `cinema-bot-app/frontend-next/pages/api/connect_runpod.ts`
- [ ] Lines 8, 169, 170, 262, 379, 382-383, 413, 422, 431, 438, 445-447: Replace Sphinx references
- [ ] Lines 372, 438: Remove or document HUME_API_KEY passing
- [ ] Review entire file for accuracy

---

### Phase 3: Backend Python Documentation Review

#### Task 9: Backend Core Files ⏳

**File:** `cinema-bot-app/backend/src/cinema-bot/server.py`
- [ ] Current status: Modified in git
- [ ] Review all functions and add docstrings
- [ ] Document all endpoints
- [ ] Add inline comments for complex logic

**File:** `cinema-bot-app/backend/src/cinema-bot/cinema_bot.py`
- [ ] Lines 225, 229, 230: Document SPHINX_* backward compatibility or remove
- [ ] Lines 57, 305, 338: Review Hume removal comments
- [ ] Review all functions and add docstrings
- [ ] Add inline comments for complex logic

**File:** `cinema-bot-app/backend/src/cinema-bot/cinema_script.py`
- [ ] Review flow definitions
- [ ] Add docstrings to all functions
- [ ] Document conversation flow structure

**File:** `cinema-bot-app/backend/src/cinema-bot/mcp_client.py`
- [ ] Review MCP integration logic
- [ ] Add docstrings to all functions
- [ ] Document stdio communication

**File:** `cinema-bot-app/backend/src/cinema-bot/mcp_video_tools.py`
- [ ] Review video tool implementations
- [ ] Add docstrings to all functions
- [ ] Document tool parameters

**File:** `cinema-bot-app/backend/src/cinema-bot/custom_flow_manager.py`
- [ ] Review flow state management
- [ ] Add docstrings to all functions
- [ ] Document state transitions

**File:** `cinema-bot-app/backend/src/cinema-bot/status_utils.py`
- [ ] Review status update logic
- [ ] Add docstrings to all functions
- [ ] Document message formats

**File:** `cinema-bot-app/backend/src/cinema-bot/cloudwatch_logger.py`
- [ ] Review CloudWatch integration
- [ ] Add docstrings to all functions
- [ ] Document AWS configuration requirements

**File:** `cinema-bot-app/backend/src/cinema-bot/cleanup_daily_rooms.py`
- [ ] Review cleanup logic
- [ ] Add docstrings to all functions
- [ ] Document usage instructions

**Files:** `__init__.py`, `__main__.py`
- [ ] Review module structure
- [ ] Add module-level docstrings
- [ ] Document CLI entry point

---

### Phase 4: MCP Server Documentation Review

#### Task 10: MCP Server Files ⏳

**File:** `mcp/server.py`
- [ ] Review GoodCLIPS integration
- [ ] Add docstrings to all functions
- [ ] Document API endpoints used

**File:** `mcp/mock_server.py`
- [ ] Review mock implementation
- [ ] Add docstrings to all functions
- [ ] Document keyword search algorithm

**File:** `mcp/config.py`
- [ ] Review configuration options
- [ ] Add docstrings
- [ ] Document all config variables

**File:** `mcp/goodclips_client.py`
- [ ] Review API client implementation
- [ ] Add docstrings to all functions
- [ ] Document API request/response formats

**File:** `mcp/video_playback_service_mpv.py` ⚠️ ACTIVE - RUNS ON PI
- [ ] Review MPV integration
- [ ] Add docstrings to all functions
- [ ] Document Pi deployment process
- [ ] Add README section about Pi files

**Files:** `mcp/video_playback_service_vlc.py`, `mcp/video_playback_service.py`
- [ ] Mark as alternative implementations
- [ ] Add docstrings
- [ ] Document differences from MPV version

**File:** `mcp/video_player.py`
- [ ] Review utility functions
- [ ] Add docstrings
- [ ] Document usage

**Files:** `mcp/pi_daily_client_rtvi.py`, `mcp/pi_daily_client_rtvi_v2.py` ⚠️ ACTIVE - RUN ON PI
- [ ] Review Pi Daily client implementations
- [ ] Add docstrings to all functions
- [ ] Document V2 improvements
- [ ] Add README section about Pi files

**Other Pi Client Variants:**
- [ ] Identify which are test/development versions
- [ ] Consider moving to `/mcp/archive/` or `/mcp/tests/`
- [ ] Document which version is production

**Test Scripts:** `test_pi_audio.py`, `test_audio_config.py`, `test_audio_transcribe.py`
- [ ] Move to `/mcp/tests/` directory
- [ ] Add docstrings
- [ ] Document test purposes

**File:** `generate_static.py`
- [ ] Review purpose
- [ ] Add docstrings
- [ ] Document usage

---

### Phase 5: Frontend Component Documentation

#### Task 11: Frontend Pages & Components ⏳

**File:** `cinema-bot-app/frontend-next/pages/index.tsx` (MODIFIED)
- [ ] Current status: Modified in git
- [ ] Review all React components
- [ ] Add JSDoc comments to functions
- [ ] Document props interfaces
- [ ] Add inline comments for complex logic

**File:** `cinema-bot-app/frontend-next/components/ChatLog.tsx` (MODIFIED)
- [ ] Current status: Modified in git
- [ ] Add JSDoc comments
- [ ] Document props interfaces
- [ ] Add inline comments

**File:** `cinema-bot-app/frontend-next/components/LoadingSpinner.tsx`
- [ ] Add JSDoc comments
- [ ] Document props

**File:** `cinema-bot-app/frontend-next/components/AudioDeviceSelector.tsx`
- [ ] Add JSDoc comments
- [ ] Document props and usage

**File:** `cinema-bot-app/frontend-next/components/PiAudioDeviceSelector.tsx`
- [ ] Add JSDoc comments
- [ ] Document props and usage

**Files:** `_app.tsx`, `_document.tsx`
- [ ] Add JSDoc comments
- [ ] Document Next.js customizations

---

### Phase 6: API Routes Documentation

#### Task 12: API Routes ⏳

**File:** `pages/api/connect.ts`
- [ ] Add JSDoc comments to all functions
- [ ] Document endpoint purpose and parameters
- [ ] Document response format

**File:** `pages/api/connect_local.ts`
- [ ] Add JSDoc comments
- [ ] Document local vs cloud differences
- [ ] Document configuration

**File:** `pages/api/connect_runpod.ts` (Already covered in Task 8)
- [ ] See Task 8 for reference cleanup
- [ ] Add JSDoc comments
- [ ] Document RunPod configuration

**File:** `pages/api/needs_help.ts`
- [ ] Add JSDoc comments
- [ ] Document purpose and usage

**File:** `pages/api/trigger_video.ts`
- [ ] Add JSDoc comments
- [ ] Document video trigger mechanism

**File:** `pages/api/cleanup_pi.ts`
- [ ] Add JSDoc comments
- [ ] Document cleanup process

**File:** `pages/api/start_pi_client.ts` ⚠️ STARTS PI PROCESSES
- [ ] Add JSDoc comments
- [ ] Document Pi process startup
- [ ] Document error handling

**Files:** `pages/api/pi/audio-devices.ts`, `pages/api/pi/audio-device.ts`
- [ ] Add JSDoc comments
- [ ] Document Pi audio device API
- [ ] Document usage

---

### Phase 7: Scripts & Configuration

#### Task 13: Scripts Review ⏳

**File:** `cinema-bot-app/backend/build.sh`
- [ ] Review build process
- [ ] Add comments
- [ ] Document usage

**File:** `start-local.sh`
- [ ] Review startup process
- [ ] Add comments
- [ ] Document prerequisites

**File:** `start-cloud.sh`
- [ ] Review cloud startup
- [ ] Add comments
- [ ] Document cloud configuration

**File:** `stop-local.sh`
- [ ] Review stop process
- [ ] Add comments

**File:** `cleanup_and_setup.sh`
- [ ] Review cleanup logic
- [ ] Add comments
- [ ] Document usage

**File:** `mcp/deploy_to_pi.sh`
- [ ] Review Pi deployment
- [ ] Add comments
- [ ] Document Pi setup requirements

---

### Phase 8: Documentation Consolidation

#### Task 14: Consolidate Documentation ⏳

**Root Documentation Review:**
- [ ] `CLAUDE.md` - Already up-to-date ✅
- [ ] `README.md` - Review and update
- [ ] `ARCHITECTURE.md` - Review and update
- [ ] `DEPLOYMENT.md` - Review and update
- [ ] `DEBUGGING_GUIDE.md` - Review and update
- [ ] `STARTUP.md` - Review and update

**Documentation to Consolidate:**
- [ ] Review if these can be merged or archived:
  - `REFACTORING_SUMMARY.md`
  - `AUDIO_DEVICE_SETUP.md`
  - `PI_AUDIO_FIX.md`
  - `PI_AUDIO_TESTING.md`
  - `PI_AUDIO_TESTING_NEW.md`
  - `STATIC_NOISE_SOLUTION.md`
  - `VOICE_BOT_SOLUTION.md`
  - `WSL2_PORT_FORWARDING_SETUP.md`
  - `project_status.md`
  - `microservices_database_plan.md`

**Suggestion:** Create `/docs/archive/` or `/docs/troubleshooting/` directories

**Component Documentation:**
- [ ] `cinema-bot-app/README.md` - Review
- [ ] `mcp/README.md` - Review
- [ ] `mcp/PI_AUDIO_FIX_EXPLANATION.md` - Consider consolidating

---

### Phase 9: Dependency Cleanup

#### Task 15: Remove Unused Dependencies ⏳

**File:** `cinema-bot-app/frontend-next/package.json`
- [ ] Review Cartesia TTS dependency (unused - Cinema Chat uses video, not TTS)
- [ ] Review all dependencies for actual usage
- [ ] Remove unused packages
- [ ] Update package-lock.json

**File:** `cinema-bot-app/backend/requirements.txt`
- [ ] Review all Python dependencies
- [ ] Remove unused packages
- [ ] Verify versions are appropriate
- [ ] Document why each package is needed (in comments)

---

### Phase 10: Environment & Security

#### Task 16: Environment Configuration ⏳

**Verify .env files are NOT in git:**
- [ ] Check `cinema-bot-app/frontend-next/.env` is gitignored
- [ ] Check `cinema-bot-app/backend/src/cinema-bot/.env` is gitignored
- [ ] Check `cinema-bot-app/backend/.env` is gitignored

**Update .env.example files:**
- [ ] `.env.example` - Ensure all Cinema Chat variables documented
- [ ] `mcp/.env.example` - Ensure all MCP variables documented
- [ ] Add comments explaining each variable
- [ ] Remove any Sphinx/Hume references

**Gitignore Review:**
- [ ] Ensure all .env files are properly gitignored
- [ ] Ensure __pycache__ is gitignored
- [ ] Ensure node_modules is gitignored
- [ ] Remove Sphinx references (lines 46, 48)

---

### Phase 11: Handoff Documentation

#### Task 17: Create Handoff Documentation ⏳

**Create:** `DEVELOPER_HANDOFF.md`
- [ ] Project overview and purpose
- [ ] Complete file structure map with descriptions
- [ ] Which files run where (local machine vs Raspberry Pi)
- [ ] Environment setup instructions
- [ ] Common workflows and tasks
- [ ] Troubleshooting guide
- [ ] Next steps and TODOs

**Create:** `FILE_STRUCTURE.md`
- [ ] Complete directory tree
- [ ] Purpose of each major directory
- [ ] Purpose of each major file
- [ ] Which files are active vs archived
- [ ] Which files run on Pi vs local

---

### Phase 12: Final Review

#### Task 18: Final Review & Commit ⏳

- [ ] Run full codebase search for "sphinx" (case-insensitive)
- [ ] Run full codebase search for "turning point" (case-insensitive)
- [ ] Run full codebase search for "hume" (case-insensitive) - allow in documentation
- [ ] Verify no TODO or FIXME comments left in code
- [ ] Verify all modified files are properly documented
- [ ] Create final cleanup commit
- [ ] Update CLEANUP_LOG.md with completion summary

---

## Summary Statistics

### Files to Modify: TBD
### Files to Delete: TBD
### Files to Create: 2 (DEVELOPER_HANDOFF.md, FILE_STRUCTURE.md)
### Documentation Files: 20+

---

## Notes & Decisions

*This section will be updated as cleanup progresses with any important decisions or findings.*

---

## Completion Summary

*This section will be filled upon completion with final statistics and handoff notes.*
