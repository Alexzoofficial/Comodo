const { state, ensureChat } = require('./_store');

module.exports = (req, res) => {
  const body = req.body || {};
  if (!body.chat_id || !body.path) return res.status(400).json({ error: 'Missing data' });
  ensureChat(body.chat_id);
  const files = state.filesByChat[body.chat_id];
  const folders = state.foldersByChat[body.chat_id];

  if (files[body.path] !== undefined) {
    delete files[body.path];
    return res.status(200).json({ status: 'deleted' });
  }

  let found = false;
  for (const key of Object.keys(files)) {
    if (key.startsWith(`${body.path}/`)) {
      delete files[key];
      found = true;
    }
  }
  for (const folder of Array.from(folders)) {
    if (folder === body.path || folder.startsWith(`${body.path}/`)) {
      folders.delete(folder);
      found = true;
    }
  }
  return found ? res.status(200).json({ status: 'deleted' }) : res.status(404).json({ error: 'Not found' });
};
