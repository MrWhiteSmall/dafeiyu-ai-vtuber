// 舞台能力展示面板 + AI 身份标识
// 纯前端，读不到后端也没关系，静态展示 + 轮播高亮。
(function () {
  var stage = document.getElementById('stage');
  if (!stage) return;

  var ITEMS = [
    { ico: '🎵', k: '点歌', v: '发「点歌 起风了」' },
    { ico: '📅', k: '签到', v: '发「签到」攒积分' },
    { ico: '🎲', k: '抽签', v: '发「抽个签」看运势' },
    { ico: '💬', k: '聊天', v: '直接说话，AI 实时接' },
    { ico: '👋', k: '欢迎', v: '进场自动问好' }
  ];

  var box = document.createElement('div');
  box.id = 'ability';

  var head = document.createElement('div');
  head.className = 'ah';
  head.innerHTML = '<b>本鱼能干的</b><span>·</span><span class="ai-badge">AI 虚拟主播</span>';
  box.appendChild(head);

  var rows = [];
  ITEMS.forEach(function (it) {
    var row = document.createElement('div');
    row.className = 'ab-item';
    row.innerHTML = '<div class="ico">' + it.ico + '</div>' +
      '<div class="txt"><div class="k">' + it.k + '</div><div class="v">' + it.v + '</div></div>';
    box.appendChild(row);
    rows.push(row);
  });

  var foot = document.createElement('div');
  foot.className = 'af';
  foot.textContent = '形象与声音均由 AI 实时生成';
  box.appendChild(foot);

  stage.appendChild(box);

  // 顶部常驻 AI 标识（合规要求：显著标识）
  var badge = document.createElement('div');
  badge.id = 'ai-label';
  badge.textContent = 'AI 虚拟主播 · 内容由 AI 实时生成';
  badge.style.cssText = [
    'position:absolute', 'left:40px', 'top:34px', 'z-index:7',
    'padding:10px 22px', 'border-radius:999px',
    'background:rgba(3,20,40,.66)', 'border:1px solid rgba(130,210,255,.42)',
    'color:#cdeaff', 'font-size:24px', 'letter-spacing:1px', 'font-weight:600',
    'font-family:"Microsoft YaHei","PingFang SC","Noto Sans SC",sans-serif',
    'box-shadow:0 8px 22px rgba(0,15,35,.35)', 'backdrop-filter:blur(6px)'
  ].join(';');
  stage.appendChild(badge);

  // 面板淡入
  setTimeout(function () { box.classList.add('show'); }, 600);

  // 轮播高亮，让观众知道下一行能干嘛
  var i = 0, timer = null;
  function tick() {
    rows.forEach(function (r) { r.classList.remove('on'); });
    rows[i % rows.length].classList.add('on');
    i++;
  }
  tick();
  timer = setInterval(tick, 2800);

  // 她说话时把面板压暗一点，别抢戏
  setInterval(function () {
    var lip = window.__songroomLipSync || 0;
    box.style.opacity = lip > 0.06 ? '0.86' : '';
  }, 400);
})();
