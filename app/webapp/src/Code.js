/***** === SETTINGS === *****/
const CFG = {
  FOLDER_ID: '1Ydw52sIeBbl-VT2ihATxiviR7sRaMgxA', // images live here
  FOLDER_STORE_LABEL_TILES: '1kUHYSn2D11seEPhUzHaSsASY81ruXKqd', // Folder to upload labeled tiles
  FOLDER_STORE_IMAGE_TILES: '1Ai6aaY3aYDO7n_uLwuEzR9JF7Vc6Y7qW', // Folder to upload image tiles
  IMAGE_SHEET: 'Sheet1',              // tab name
  TILE_SHEET: 'Sheet2',
  USER_SHEET: 'Sheet3',
  STALE_MINUTES: 30                  // reclaim if older than this
};

/***** === HELPERS === *****/
function sheet_(sheet_ind = 1) {
  if (sheet_ind == 2) {
    return SpreadsheetApp.getActive().getSheetByName(CFG.TILE_SHEET);
  } else if (sheet_ind == 3) {
    return SpreadsheetApp.getActive().getSheetByName(CFG.USER_SHEET);
  } else {
    return SpreadsheetApp.getActive().getSheetByName(CFG.IMAGE_SHEET);
  }
}

function now_() { return new Date(); }
function minutesAgo_(d) {
  return (now_().getTime() - new Date(d).getTime()) / 60000;
}

function email_() {
  // In Google Workspace, returns signed-in user email. Else may be blank.
  try { return Session.getActiveUser().getEmail() || 'anonymous'; } catch (e) { return 'anonymous'; }
}

function api(action, payload) {
  const me = email_();
  if (action === 'next') return popNext_(me);
  if (action === 'done') return payload && payload.fileId ? markDone_(payload.fileId, me) : { ok: false, message: 'fileId required' };
  if (action === 'skip') return payload && payload.fileId ? skip_(payload.fileId, me) : { ok: false, message: 'fileId required' };
  return { error: 'Unknown action.' };
}

/***** === QUEUE SEEDING === *****/
// Run once to list all images in folder into the sheet.
function initQueueFromFolder() {
  const sh = sheet_();
  const folder = DriveApp.getFolderById(CFG.FOLDER_ID);
  const files = folder.getFiles();
  
  // Get existing file IDs and names
  const existingData = sh.getDataRange().getValues();
  const existingFileIds = new Set();
  const existingFileNames = new Set();
  for (let r = 1; r < existingData.length; r++) {
    if (existingData[r][0]) existingFileIds.add(existingData[r][0]);
    if (existingData[r][1]) existingFileNames.add(existingData[r][1]);
  }
  
  const rows = [];
  while (files.hasNext()) {
    const f = files.next();
    const fileId = f.getId();
    const fileName = f.getName();
    
    // Only add if both ID and name don't already exist
    if (!existingFileIds.has(fileId) && !existingFileNames.has(fileName)) {
      rows.push([fileId, fileName, '', '', '', '']);
    }
  }
  
  if (rows.length) {
    sh.getRange(sh.getLastRow() + 1, 1, rows.length, 6).setValues(rows);
  }
}

// Optional: clear claims & done (keep file list)
function resetQueue() {
  const sh = sheet_();
  const rng = sh.getDataRange().getValues();
  for (let r = 1; r < rng.length; r++) {
    sh.getRange(r + 1, 3, 1, 4).clearContent(); // status..doneAt
  }
}

// Optional: shuffle unclaimed items
function shuffleUnclaimed() {
  const sh = sheet_();
  const data = sh.getDataRange().getValues();
  const header = data.shift();
  const claimed = [];
  const unclaimed = [];
  data.forEach(row => (row[2] ? claimed : unclaimed).push(row));
  for (let i = unclaimed.length - 1; i > 0; i--) {
    const j = Math.floor(Math.random() * (i + 1));
    [unclaimed[i], unclaimed[j]] = [unclaimed[j], unclaimed[i]];
  }
  const out = [header].concat(claimed).concat(unclaimed);
  sh.clearContents();
  sh.getRange(1, 1, out.length, out[0].length).setValues(out);
}

/***** === CORE QUEUE OPS (atomic) === *****/
function findNextRow_(data, staleMinutes) {
  // prefer: first unclaimed (skip over 'skipped' status); else reclaim stale claimed
  for (let r = 1; r < data.length; r++) {
    const status = data[r][2];
    if (!status || status === '') return r; // status empty = unclaimed
  }
  
  // Try stale claimed items
  for (let r = 1; r < data.length; r++) {
    const status = data[r][2], claimedAt = data[r][4];
    if (status === 'claimed' && claimedAt && minutesAgo_(claimedAt) >= staleMinutes) {
      return r;
    }
  }
  
  return -1;
}

function peekNext_() {
  // Peek at the next available image without claiming it
  const lock = LockService.getScriptLock();
  lock.tryLock(30000);
  try {
    const sh = sheet_();
    const rng = sh.getDataRange();
    const data = rng.getValues();
    
    const rowIdx = findNextRow_(data, CFG.STALE_MINUTES);
    if (rowIdx < 0) return { done: true, message: 'Queue empty.' };

    const fileId = data[rowIdx][0];
    const fileName = data[rowIdx][1];

    return { done: false, fileId, fileName };
  } finally {
    lock.releaseLock();
  }
}

function popNext_(requester) {
  const lock = LockService.getScriptLock();
  lock.tryLock(30000);
  try {
    const sh = sheet_();
    const rng = sh.getDataRange();
    const data = rng.getValues();
    
    const rowIdx = findNextRow_(data, CFG.STALE_MINUTES);
    if (rowIdx < 0) return { done: true, message: 'Queue empty.' };

    const sheetRow = rowIdx + 1; // 1-based with header
    const fileId = data[rowIdx][0];
    const fileName = data[rowIdx][1];

    // claim it
    sh.getRange(sheetRow, 3).setValue('claimed');        // status
    sh.getRange(sheetRow, 4).setValue(requester);        // claimedBy
    sh.getRange(sheetRow, 5).setValue(now_());           // claimedAt

    const viewLink = 'https://drive.google.com/file/d/' + fileId + '/view';
    const directLink = 'https://drive.google.com/uc?export=download&id=' + fileId;

    return { done: false, fileId, fileName, viewLink, directLink, row: sheetRow };
  } finally {
    lock.releaseLock();
  }
}

function popRandomTile_() {
  const lock = LockService.getScriptLock();
  lock.tryLock(30000);
  try {
    const folder = DriveApp.getFolderById(CFG.FOLDER_STORE_IMAGE_TILES);
    const files = folder.getFiles();
    const fileList = [];
    
    while (files.hasNext()) {
      fileList.push(files.next());
    }
    
    if (fileList.length === 0) {
      return { done: true, message: 'No tiles available.' };
    }
    
    const randomIndex = Math.floor(Math.random() * fileList.length);
    const randomFile = fileList[randomIndex];
    const fileId = randomFile.getId();
    const fileName = randomFile.getName();
    
    const viewLink = 'https://drive.google.com/file/d/' + fileId + '/view';
    const directLink = 'https://drive.google.com/uc?export=download&id=' + fileId;
    
    return { done: false, fileId, fileName, viewLink, directLink };
  } finally {
    lock.releaseLock();
  }
}

function markDone_(fileId, requester) {
  const lock = LockService.getScriptLock();
  lock.tryLock(30000);
  try {
    const sh = sheet_();
    const data = sh.getDataRange().getValues();
    for (let r = 1; r < data.length; r++) {
      if (data[r][0] === fileId && (data[r][2] === 'claimed' || data[r][2] === 'in_progress')) {
        // optional: ensure same user
        sh.getRange(r + 1, 3).setValue('done');
        sh.getRange(r + 1, 6).setValue(now_()); // doneAt
        return { ok: true };
      }
    }
    return { ok: false, message: 'Not found or not claimed/in_progress.' };
  } finally {
    lock.releaseLock();
  }
}

function markInProgress_(fileId, requester) {
  // Mark image as in_progress so it's preserved across clearStaleClaims
  const lock = LockService.getScriptLock();
  lock.tryLock(30000);
  try {
    const sh = sheet_();
    const data = sh.getDataRange().getValues();
    for (let r = 1; r < data.length; r++) {
      if (data[r][0] === fileId && data[r][2] === 'claimed') {
        sh.getRange(r + 1, 3).setValue('in_progress');
        return { ok: true };
      }
    }
    return { ok: false, message: 'Not found or not claimed.' };
  } finally {
    lock.releaseLock();
  }
}

function getInProgress_(requester) {
  // Get the in_progress image for a specific user
  const lock = LockService.getScriptLock();
  lock.tryLock(30000);
  try {
    const sh = sheet_();
    const data = sh.getDataRange().getValues();
    
    for (let r = 1; r < data.length; r++) {
      const status = data[r][2];
      const claimedBy = data[r][3];
      
      if (status === 'in_progress' && claimedBy === requester) {
        const fileId = data[r][0];
        const fileName = data[r][1];
        return { ok: true, fileId, fileName };
      }
    }
    
    return { ok: false, message: 'No in_progress work found.' };
  } finally {
    lock.releaseLock();
  }
}

function skip_(fileId, requester) {
  // Mark as skipped so it won't be picked again immediately
  const lock = LockService.getScriptLock();
  lock.tryLock(30000);
  try {
    const sh = sheet_();
    const data = sh.getDataRange().getValues();
    for (let r = 1; r < data.length; r++) {
      if (data[r][0] === fileId && data[r][2] === 'claimed') {
        sh.getRange(r + 1, 3).setValue('skipped');  // Mark as skipped (column C)
        sh.getRange(r + 1, 4, 1, 3).clearContent(); // Clear claimedBy, claimedAt, doneAt (columns D, E, F)
        return { ok: true };
      }
    }
    return { ok: false, message: 'Not found or not claimed.' };
  } finally {
    lock.releaseLock();
  }
}

function getLastTileIndexRow() {
  const lock = LockService.getScriptLock();
  lock.tryLock(30000);
  try {
    const sh = sheet_(2);
    const data = sh.getDataRange().getValues();
    let lastTileIndex = 0;
    let row = 1;
    for (let r = 1; r < data.length; r++) {
      if (data[r][0] > lastTileIndex) {
        lastTileIndex = data[r][0];
      }
      row = r;
    }
    lastTileIndex += 1
    return [lastTileIndex, row];
  } finally {
    lock.releaseLock();
  }
}

function getUserList() {
  const lock = LockService.getScriptLock();
  lock.tryLock(30000);
  try {
    const sh = sheet_(3);
    const data = sh.getDataRange().getValues();
    const users = [];
    for (let r = 1; r < data.length; r++) {
      if (data[r][0]) {
        users.push(data[r][0]);
      }
    }
    return users;
  } finally {
    lock.releaseLock();
  }
}

function createNewUser(name) {
  const lock = LockService.getScriptLock();
  lock.tryLock(30000);
  try {
    const sh = sheet_(3);
    const lastRow = sh.getLastRow();
    sh.getRange(lastRow + 1, 1).setValue(name);
    return { ok: true };
  } finally {
    lock.releaseLock();
  }
}

function updateTileTracker(row, source_img_fname, tile_mask_id, file_mask_fname, tile_img_id, tile_img_fname, annotatedBy) {
  const lock = LockService.getScriptLock();
  lock.tryLock(30000);
  try {
    const sh = sheet_(2);
    sh.getRange(row, 1).setValue(`${row}`);
    sh.getRange(row, 2).setValue(source_img_fname);
    sh.getRange(row, 3).setValue(tile_mask_id);
    sh.getRange(row, 4).setValue(file_mask_fname);
    sh.getRange(row, 5).setValue(tile_img_id);
    sh.getRange(row, 6).setValue(tile_img_fname);
    sh.getRange(row, 7).setValue(annotatedBy);
    sh.getRange(row, 8).setValue(now_());
    return 1;

  } finally {
    lock.releaseLock();
    return 0;
  }
}

function clean_exit(fileId, requester) {
  // turn a claimed row back to unclaimed
  const lock = LockService.getScriptLock();
  lock.tryLock(30000);
  try {
    const sh = sheet_();
    const data = sh.getDataRange().getValues();
    for (let r = 1; r < data.length; r++) {
      if (data[r][0] === fileId && data[r][2] === 'claimed') {
        sh.getRange(r + 1, 3, 1, 4).clearContent(); // status..doneAt
        return { ok: true };
      }

    }
  } finally {
    lock.releaseLock();
  }
}

function clearStaleClaims() {
  const lock = LockService.getScriptLock();
  lock.tryLock(30000);
  try {
    const sh = sheet_(1);
    const data = sh.getDataRange().getValues();
    
    for (let r = 1; r < data.length; r++) {
      const status = data[r][2]; // Column C (status)
      const doneAt = data[r][5]; // Column F (doneAt)
      
      // Clear stale claimed images and skipped images (but preserve in_progress)
      if ((status === 'claimed' && !doneAt) || status === 'skipped') {
        sh.getRange(r + 1, 3, 1, 4).clearContent(); // Clear columns C-F
      }
      // Note: in_progress status is intentionally NOT cleared
    }
    
    return { ok: true };
  } finally {
    lock.releaseLock();
  }
}

function getCompletedFileIds() {
  const lock = LockService.getScriptLock();
  lock.tryLock(30000);
  try {
    const sh = sheet_();
    const data = sh.getDataRange().getValues();
    const completedIds = [];
    
    Logger.log('Scanning for completed images...');
    
    for (let r = 1; r < data.length; r++) {
      const status = data[r][2]; // Column C (status)
      if (status === 'done') {
        completedIds.push(data[r][0]); // Column A (fileId)
      }
    }
    
    Logger.log('Found ' + completedIds.length + ' completed images');
    
    return { ok: true, fileIds: completedIds };
  } catch (error) {
    Logger.log('Error in getCompletedFileIds: ' + error.toString());
    return { ok: false, error: error.toString() };
  } finally {
    lock.releaseLock();
  }
}

/***** === WEB APP ENDPOINTS === *****/
function doPost(e) {
  const req = e && e.postData && e.postData.contents ? JSON.parse(e.postData.contents) : {};

  if (req.action === 'upload_tiles') {
    if (req.baseName) {
      if (Array.isArray(req.items)) {

        const label_parent = DriveApp.getFolderById(CFG.FOLDER_STORE_LABEL_TILES);
        const image_parent = DriveApp.getFolderById(CFG.FOLDER_STORE_IMAGE_TILES);

        // Get the last tile index from the sheet and update file name accordingly
        const [lastTileIndex, row] = getLastTileIndexRow();
        for (var k = 0; k < req.items.length; k++) {
          var it = req.items[k];
          // PNG
          var pngBytes = Utilities.base64Decode(it.png_b64);
          const pngFileName = (`image_${lastTileIndex + k + 1}.png`);
          var pngBlob = Utilities.newBlob(pngBytes, 'image/png', pngFileName);
          var pngFile = image_parent.createFile(pngBlob);

          // CSV (text)
          var csvBytes = Utilities.base64Decode(it.csv_b64);
          const csvFileName = (`tile_${lastTileIndex + k + 1}.csv`);
          var csvBlob = Utilities.newBlob(csvBytes, 'text/csv', csvFileName);
          var csvFile = label_parent.createFile(csvBlob);

          success = updateTileTracker(row + k + 1, req.source_img_fname, pngFile.getId(), pngFileName, csvFile.getId(), csvFileName, req.author || 'anonymous');

        }
        return json_({ ok: true });
      } else {
        return json_({ error: 'items not Array' })
      }
    } else {
      return json_({ error: 'baseName incorrect' })
    }
  }

  const me = (function () { try { return Session.getActiveUser().getEmail() || 'anonymous'; } catch (e) { return 'anonymous'; } })();
  if (req.action === 'peek_next') return json_(peekNext_());
  if (req.action === 'next') return json_(popNext_(req.user || me));
  if (req.action === 'done' && req.fileId) return json_(markDone_(req.fileId, me));
  if (req.action === 'mark_in_progress' && req.fileId) return json_(markInProgress_(req.fileId, req.user || me));
  if (req.action === 'get_in_progress') return json_(getInProgress_(req.user || me));
  if (req.action === 'skip' && req.fileId) return json_(skip_(req.fileId, me));
  if (req.action === 'random_tile') return json_(popRandomTile_());
  if (req.action === 'user_list') return json_({ users: getUserList() });
  if (req.action === 'create_user' && req.name) return json_(createNewUser(req.name));
  if (req.action === 'clean_exit' && req.fileId) return json_(clean_exit(req.fileId, me));
  if (req.action === 'get_completed_ids') return json_(getCompletedFileIds());
  return json_({ error: 'Unknown action: ' + req.action });
}

function json_(obj) {
  return ContentService.createTextOutput(JSON.stringify(obj)).setMimeType(ContentService.MimeType.JSON);
}

function doGet(e) {
  Logger.log('doGet called with parameters: ' + JSON.stringify(e.parameter));
  
  if (e && e.parameter && e.parameter.raw) {
    try {
      const fileId = e.parameter.raw;
      Logger.log('Fetching file with ID: ' + fileId);
      
      const file = DriveApp.getFileById(fileId);
      const blob = file.getBlob();
      const b64 = Utilities.base64Encode(blob.getBytes());
      
      Logger.log('Returning base64 data, length: ' + b64.length);
      
      return ContentService
        .createTextOutput(b64)
        .setMimeType(ContentService.MimeType.TEXT);
    } catch (error) {
      Logger.log('Error in doGet: ' + error.toString());
      return ContentService
        .createTextOutput('Error: ' + error.toString())
        .setMimeType(ContentService.MimeType.TEXT);
    }
  }

  Logger.log('No raw parameter, returning OK page');
  return HtmlService.createHtmlOutput("OK");
}

function respond_(obj) {
  return ContentService.createTextOutput(JSON.stringify(obj))
    .setMimeType(ContentService.MimeType.JSON);
}
