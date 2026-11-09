/* 左侧信息栏：正在播放 / 歌词 + 本场 token 消耗
   数据源：
   - 字幕口型服务 http://127.0.0.1:5500/state（歌词与说话都从这里来）
   - ./token_stats.json（由 tools/llm_fallback.py 每次调用后写入，走 12345 静态服务，同源）
*/
(function () {
  const S = document.createElement('style');
  S.textContent = `
  #leftpanel{position:absolute;left:44px;top:468px;max-height:404px;overflow:hidden;width:400px;z-index:5;
    padding:26px 26px 20px;border-radius:26px;
    background:linear-gradient(160deg,rgba(6,30,56,.78),rgba(4,18,38,.62));
    border:1px solid rgba(120,190,255,.22);box-shadow:0 10px 40px rgba(0,10,30,.35);
    backdrop-filter:blur(8px);font-family:"Microsoft YaHei","PingFang SC",sans-serif;color:#dcecff}
  #leftpanel .lp-title{display:flex;align-items:center;gap:10px;font-size:22px;font-weight:600;
    color:#bcdcff;letter-spacing:1px;margin-bottom:14px}
  #leftpanel .lp-dot{width:9px;height:9px;border-radius:50%;background:#5fd7ff;
    box-shadow:0 0 10px #5fd7ff;animation:lppulse 1.8s ease-in-out infinite}
  @keyframes lppulse{0%,100%{opacity:.45}50%{opacity:1}}
  #leftpanel .lp-song{font-size:26px;font-weight:700;color:#eaf6ff;line-height:1.35;
    margin:2px 0 12px;text-shadow:0 2px 12px rgba(40,140,255,.45)}
  #leftpanel .lp-queue{display:block;margin-top:7px;font-size:15px;font-weight:600;
    color:#9fd0f0;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
  #leftpanel .lp-lyrics{min-height:96px;max-height:150px;overflow:hidden;display:flex;flex-direction:column;gap:8px}
  #leftpanel .lp-line{font-size:21px;line-height:1.5;color:rgba(200,225,255,.62);
    transition:color .25s,transform .25s}
  #leftpanel .lp-line.latest{color:#ffffff;transform:translateX(2px)}
  #leftpanel .lp-hr{height:1px;margin:16px 0 14px;
    background:linear-gradient(90deg,rgba(120,190,255,.35),rgba(120,190,255,0))}
  #leftpanel .lp-kv{display:flex;justify-content:space-between;align-items:baseline;
    font-size:19px;color:rgba(190,215,245,.8)}
  #leftpanel .lp-val{font-size:30px;font-weight:700;color:#7fe0ff;
    font-variant-numeric:tabular-nums;letter-spacing:.5px}
  #leftpanel .lp-sub{margin-top:6px;font-size:15px;color:rgba(160,190,225,.55)}
  #leftpanel .lp-today{display:flex;gap:10px;margin-top:14px}
  #leftpanel .lp-cell{flex:1;padding:9px 6px 8px;border-radius:14px;text-align:center;
    background:linear-gradient(160deg,rgba(90,170,255,.14),rgba(90,170,255,.04));
    border:1px solid rgba(130,205,255,.16)}
  #leftpanel .lp-cell b{display:block;font-size:26px;font-weight:800;color:#ffe1a8;
    font-variant-numeric:tabular-nums;line-height:1.1}
  #leftpanel .lp-cell span{display:block;margin-top:3px;font-size:13px;color:rgba(180,210,240,.72)}
  `;
  document.head.appendChild(S);

  const box = document.createElement('div');
  box.id = 'leftpanel';
  box.innerHTML = `
    <div class="lp-title"><span class="lp-dot"></span><span id="lp-head">刚才说到</span></div>
    <div class="lp-song" id="lp-song"></div>
    <div class="lp-lyrics" id="lp-lyrics"></div>
    <div class="lp-hr"></div>
    <div class="lp-kv"><span>本场消耗 token</span><span class="lp-val" id="lp-token">–</span></div>
    <div class="lp-sub" id="lp-sub">等她说第一句话</div>
    <div class="lp-today">
      <div class="lp-cell"><b id="lp-users">–</b><span>今天打过招呼</span></div>
      <div class="lp-cell"><b id="lp-replies">–</b><span>互动回复</span></div>
      <div class="lp-cell"><b id="lp-gifts">–</b><span>收到礼物</span></div>
    </div>
  `;
  document.body.appendChild(box);

  const elHead = box.querySelector('#lp-head');
  const elSong = box.querySelector('#lp-song');
  const elLyrics = box.querySelector('#lp-lyrics');
  const elToken = box.querySelector('#lp-token');
  const elSub = box.querySelector('#lp-sub');

  let lastId = null;
  let songName = '';
  let songAt = 0;
  let lines = [];          // 最近几行（歌名之后的内容当歌词）
  let queueInfo = '';      // 「后面还排着 2 首：稻香、起风了」

  function renderSong() {
    elSong.textContent = songName ? '♪ ' + songName : '';
    if (songName && queueInfo) {
      const q = document.createElement('span');
      q.className = 'lp-queue';
      q.textContent = queueInfo;
      elSong.appendChild(q);
    }
  }

  function pushLine(t) {
    if (!t) return;
    lines.push(t);
    if (lines.length > 4) lines.shift();
    render();
  }

  function render() {
    elLyrics.innerHTML = '';
    lines.forEach((t, i) => {
      const d = document.createElement('div');
      d.className = 'lp-line' + (i === lines.length - 1 ? ' latest' : '');
      d.textContent = t;
      elLyrics.appendChild(d);
    });
  }

  // ---- 字幕/歌词 ----
  async function pollCaption() {
    try {
      const r = await fetch('http://127.0.0.1:5500/state', { cache: 'no-store' });
      const d = await r.json();
      const text = (d.text || '').trim();
      const id = String(d.id) + ':' + String(d.at);
      if (!text || id === lastId) return;
      lastId = id;
      if (text.startsWith('♪')) {
        songName = text.replace(/^♪\s*/, '').trim();
        songAt = Date.now();
        lines = [];
        renderSong();
        elHead.textContent = '正在播放';
        render();
      } else {
        if (Date.now() - songAt > 6 * 60 * 1000) {   // 6 分钟没歌了，当说话内容
          elHead.textContent = '刚才说到';
          songName = '';
          queueInfo = '';
          renderSong();
        }
        pushLine(text);
      }
    } catch (e) { /* 服务没起就安静 */ }
  }
  setInterval(pollCaption, 400);
  pollCaption();

  // ---- token ----
  let lastToken = -1;
  async function pollToken() {
    try {
      const r = await fetch('./token_stats.json?t=' + Date.now(), { cache: 'no-store' });
      const d = await r.json();
      const total = d.total_tokens != null ? d.total_tokens : (d.total || 0);
      elToken.textContent = total.toLocaleString('en-US');
      const p = (d.prompt_tokens != null ? d.prompt_tokens : (d.prompt || 0)).toLocaleString('en-US');
      const c = (d.completion_tokens != null ? d.completion_tokens : (d.completion || 0)).toLocaleString('en-US');
      elSub.textContent = `${d.calls || 0} 次调用 · 输入 ${p} / 输出 ${c}`;
    } catch (e) {
      if (elToken.textContent === '–') elToken.textContent = '0';
    }
  }
  setInterval(pollToken, 4000);
  pollToken();

  // ---- 今日台面数据（人数 / 互动 / 礼物），由 utils/msg_log.py 累计 ----
  const elUsers = box.querySelector('#lp-users');
  const elReplies = box.querySelector('#lp-replies');
  const elGifts = box.querySelector('#lp-gifts');
  async function pollToday() {
    try {
      const r = await fetch('./live_stats.json?t=' + Date.now(), { cache: 'no-store' });
      const d = await r.json();
      elUsers.textContent = d.users || 0;
      elReplies.textContent = d.replies || 0;
      elGifts.textContent = d.gifts || 0;
      elGifts.title = '累计 ' + (d.coins || 0) + ' 抖币';
    } catch (e) { /* 忽略 */ }
  }
  setInterval(pollToday, 5000);
  pollToday();

  // ---- 点歌队列（由 utils/my_handle.py 写入 Live2D/song_queue.json）----
  function shortTitle(t) {
    return String(t || '').replace(/\s*-\s*[^-]*$/, '') || String(t || '');
  }
  async function pollQueue() {
    try {
      const r = await fetch('./song_queue.json?t=' + Date.now(), { cache: 'no-store' });
      const d = await r.json();
      const q = d.queue || [];
      const playing = d.playing && d.playing.title ? d.playing.title : '';

      // "正在播放"以队列状态为准，页面中途刷新也能对上
      if (playing) {
        if (playing !== songName) {
          songName = playing;
          renderSong();
        }
        songAt = Date.now();
        elHead.textContent = '正在播放';
      } else if (songName && Date.now() - songAt > 10000) {
        songName = '';
        queueInfo = '';
        elHead.textContent = '刚才说到';
        renderSong();
      }

      let info = '';
      if (q.length) {
        const names = q.slice(0, 2).map(x => shortTitle(x.title)).join('、');
        info = '后面还排着 ' + q.length + ' 首：' + names + (q.length > 2 ? '…' : '');
      }
      if (info !== queueInfo) {
        queueInfo = info;
        if (songName) renderSong();
      }
    } catch (e) { /* 没文件就安静 */ }
  }
  setInterval(pollQueue, 2500);
  pollQueue();
})();
