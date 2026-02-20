const state = globalThis.__DEVX_STATE__ || {
  chats: {},
  current_chat: null,
  projects: {},
  filesByChat: {},
  foldersByChat: {}
};

globalThis.__DEVX_STATE__ = state;

function ensureChat(chatId) {
  if (!state.filesByChat[chatId]) state.filesByChat[chatId] = {};
  if (!state.foldersByChat[chatId]) state.foldersByChat[chatId] = new Set();
}

function sanitizeName(name) {
  const clean = String(name || "")
    .split("")
    .filter((c) => /[a-zA-Z0-9_-]/.test(c))
    .join("")
    .trim();
  return clean || `Project-${crypto.randomUUID().slice(0, 6)}`;
}

function fileTree(chatId) {
  ensureChat(chatId);
  const files = Object.keys(state.filesByChat[chatId]);
  const folders = Array.from(state.foldersByChat[chatId]);
  const tree = [];
  for (const path of folders.sort()) {
    const segs = path.split("/");
    tree.push({ type: "folder", name: segs[segs.length - 1], path });
  }
  for (const path of files.sort()) {
    const segs = path.split("/");
    tree.push({ type: "file", name: segs[segs.length - 1], path });
  }
  return tree;
}

module.exports = { state, ensureChat, sanitizeName, fileTree };
