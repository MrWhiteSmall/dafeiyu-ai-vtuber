/* 大章鱼 · 直播间小游戏（弹窗演出）
 * 三个游戏共用同一个「游戏窗口」：
 *   ① 猜拳      弹幕发「猜拳」开局，再发「石头/剪刀/布」出拳，5 局制
 *   ② 贪吃蛇    弹幕发「玩贪吃蛇」，她自己玩 40 秒，观众看着
 *   ③ 草稿画    弹幕发「画个 小猫」，调 paint_service 生成抽象草稿
 * 同一时刻只允许一个游戏；游戏命令与动作触发互不干扰。
 */
(function () {
  'use strict';

  var PAINT_API = 'http://127.0.0.1:8899';
  var SAY_API = 'http://127.0.0.1:8082';

  // 让主程序念一句话（游戏里的提示/揭晓走这条，别自己合成）
  function say(text) {
    if (!text) return;
    try {
      fetch(SAY_API + '/say', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ content: text, username: '观众' })
      }).catch(function () {});
    } catch (e) { /* 主程序没起来就算了，别挡住游戏 */ }
  }
  var box = document.getElementById('gamebox');
  if (!box) { console.warn('[game] 缺少 #gamebox'); return; }

  var elTitle = document.getElementById('gb-title');
  var elSub = document.getElementById('gb-sub');
  var elBody = document.getElementById('gb-body');
  var elBar = document.getElementById('gb-bar');
  var elHint = document.getElementById('gb-hint');

  var current = null;        // 'rps' | 'snake' | 'doodle'
  var closeTimer = null, tickTimer = null, barTimer = null;

  function play(name, sec) {
    try { if (window.__feiyuPlay) window.__feiyuPlay(name, sec); } catch (e) {}
  }

  var CLOSE_TOKEN = 0;   // 每次开会话 +1，旧会话排的稍后关闭到点会失效
  function closeLater(ms) {
    var t = CLOSE_TOKEN;
    setTimeout(function () { if (t === CLOSE_TOKEN) close(); }, ms);
  }

  function open(title, sub, hint, seconds) {
    CLOSE_TOKEN += 1;
    current = title;
    elTitle.textContent = title;
    elSub.textContent = sub || '';
    elHint.textContent = hint || '';
    elBody.innerHTML = '';
    box.classList.add('show');
    box.dataset.game = title;
    document.body.classList.add('game-on');
    startBar(seconds || 20);
  }

  function close() {
    CLOSE_TOKEN += 1;
    box.classList.remove('show');
    document.body.classList.remove('game-on');
    current = null;
    clearTimeout(closeTimer); closeTimer = null;
    clearInterval(tickTimer); tickTimer = null;
    clearInterval(barTimer); barTimer = null;
    elBar.style.width = '100%';
    setTimeout(function () { if (!current) elBody.innerHTML = ''; }, 400);
  }

  var barLeft = 0, barTotal = 1;
  function startBar(sec) {
    clearInterval(barTimer);
    barTotal = sec * 1000; barLeft = barTotal;
    elBar.style.width = '100%';
    barTimer = setInterval(function () {
      barLeft -= 100;
      elBar.style.width = Math.max(0, (barLeft / barTotal) * 100) + '%';
      if (barLeft <= 0) { clearInterval(barTimer); close(); }
    }, 100);
  }
  function resetBar(sec) {
    clearInterval(barTimer);
    barTotal = sec * 1000; barLeft = barTotal;
    elBar.style.width = '100%';
    barTimer = setInterval(function () {
      barLeft -= 100;
      elBar.style.width = Math.max(0, (barLeft / barTotal) * 100) + '%';
      if (barLeft <= 0) { clearInterval(barTimer); close(); }
    }, 100);
  }

  /* ───────────── ① 猜拳 ───────────── */
  var HANDS = {
    '石头': { emo: '✊', name: '石头' },
    '剪刀': { emo: '✌️', name: '剪刀' },
    '布':   { emo: '✋', name: '布' }
  };
  // 她自己的出拳姿势图（875x1200 抠图版）
  var POSE_SRC = {
    '石头': 'rps-rock_t.png',
    '剪刀': 'rps-scissor_t.png',
    '布':   'rps-paper_t.png'
  };
  var RPS = { round: 0, win: 0, lose: 0, draw: 0, waiting: false, maxRound: 5 };

  function rpsOpen() {
    RPS.round = 0; RPS.win = 0; RPS.lose = 0; RPS.draw = 0;
    open('猜拳 · 准备中', '她正在搓手', '发弹幕：石头 / 剪刀 / 布', 14);
    play('count', 3);
    closeTimer = setTimeout(rpsRound, 1200);
  }

  function rpsRound() {
    if (current !== '猜拳 · 第 1 局' && current && current.indexOf('猜拳') !== 0) return;
    RPS.round += 1;
    RPS.waiting = true;
    elTitle.textContent = '猜拳 · 第 ' + RPS.round + ' 局';
    elSub.textContent = '战绩 ' + RPS.win + ' 胜 ' + RPS.lose + ' 负 ' + RPS.draw + ' 平';
    elHint.textContent = '发弹幕：石头 / 剪刀 / 布';
    elBody.innerHTML =
      '<div class="gb-hands">' +
      '<div class="gb-hand"><b>✊</b><span>石头</span></div>' +
      '<div class="gb-hand"><b>✌️</b><span>剪刀</span></div>' +
      '<div class="gb-hand"><b>✋</b><span>布</span></div>' +
      '</div>' +
      '<div class="gb-tip">选一个发弹幕，本鱼同时出拳</div>';
    resetBar(14);
    play('count', 2.2);
    closeTimer = setTimeout(function () {
      if (RPS.waiting) { finishRps('没人接拳，这局算我赢～'); }
    }, 14000);
  }

  function judge(a, b) {
    if (a === b) return 0;
    if ((a === '石头' && b === '剪刀') || (a === '剪刀' && b === '布') || (a === '布' && b === '石头')) return 1;
    return -1;
  }

  function rpsPlay(userHand) {
    if (!RPS.waiting) return;
    RPS.waiting = false;
    clearTimeout(closeTimer);
    var keys = ['石头', '剪刀', '布'];
    var mine = keys[Math.floor(Math.random() * 3)];
    var r = judge(userHand, mine);
    if (r > 0) RPS.win++; else if (r < 0) RPS.lose++; else RPS.draw++;

    var verdict = r > 0 ? '你赢了！' : (r < 0 ? '本鱼赢啦～' : '平局，再来！');
    var color = r > 0 ? '#8ef0c0' : (r < 0 ? '#ffb27a' : '#ffd479');
    elTitle.textContent = '猜拳 · 第 ' + RPS.round + ' 局';
    elSub.textContent = '战绩 ' + RPS.win + ' 胜 ' + RPS.lose + ' 负 ' + RPS.draw + ' 平';
    elBody.innerHTML =
      '<div class="gb-vs">' +
      '<div class="gb-side"><b>' + HANDS[userHand].emo + '</b><span>你 · ' + userHand + '</span></div>' +
      '<div class="gb-mid" style="color:' + color + '">' + verdict + '</div>' +
      '<div class="gb-side"><b><img class="gb-pose" alt="" src="./assets/octo/' + POSE_SRC[mine] + '"></b>' +
      '<span>大章鱼 · ' + mine + '</span></div>' +
      '</div>';
    play(r > 0 ? 'lieflat' : 'cheer', 2.6);
    resetBar(9);
    closeTimer = setTimeout(function () {
      if (RPS.round >= RPS.maxRound) {
        var s = RPS.win > RPS.lose ? '今天是我输了，你厉害。'
              : (RPS.win < RPS.lose ? '本鱼今天手气好，明天再来。'
              : '打成平手，改天再战。');
        finishRps(s);
      } else {
        rpsRound();
      }
    }, 4200);
  }

  function finishRps(text) {
    clearTimeout(closeTimer); clearInterval(barTimer);
    elTitle.textContent = '猜拳 · 收场';
    elSub.textContent = '战绩 ' + RPS.win + ' 胜 ' + RPS.lose + ' 负 ' + RPS.draw + ' 平';
    elHint.textContent = '想再来就发「猜拳」';
    elBody.innerHTML = '<div class="gb-end">' + text + '</div>';
    elBar.style.width = '0%';
    RPS.waiting = false;
    closeLater(4200);
  }

  /* ───────────── ② 贪吃蛇 ───────────── */
  var snake = null;
  function snakeOpen() {
    open('看她玩 · 贪吃蛇', '她自己玩，你们围观', '40 秒一局，撞墙就结束', 40);
    elBody.innerHTML =
      '<div class="gb-snake"><canvas id="snake-cv" width="480" height="480"></canvas>' +
      '<div class="gb-score">得分 <b id="snake-sc">0</b> · 最高 <b id="snake-best">' + (snakeBest || 0) + '</b></div></div>';
    play('laptop', 40);
    startSnake();
  }

  var snakeBest = 0;
  function startSnake() {
    var cv = document.getElementById('snake-cv');
    if (!cv) return;
    var ctx = cv.getContext('2d');
    var N = 20, cell = cv.width / N;
    var body = [{ x: 10, y: 10 }, { x: 9, y: 10 }, { x: 8, y: 10 }];
    var dir = { x: 1, y: 0 }, food = { x: 15, y: 10 }, score = 0, dead = false;
    var speed = 150, acc = 0, last = performance.now();

    function rndFood() {
      for (var i = 0; i < 200; i++) {
        var f = { x: Math.floor(Math.random() * N), y: Math.floor(Math.random() * N) };
        if (!body.some(function (b) { return b.x === f.x && b.y === f.y; })) { food = f; return; }
      }
    }
    rndFood();

    function blocked(x, y) {
      if (x < 0 || y < 0 || x >= N || y >= N) return true;
      return body.some(function (b) { return b.x === x && b.y === y; });
    }

    function chooseDir() {
      var h = body[0];
      var cands = [
        { d: { x: 1, y: 0 }, ok: false }, { d: { x: -1, y: 0 }, ok: false },
        { d: { x: 0, y: 1 }, ok: false }, { d: { x: 0, y: -1 }, ok: false }
      ];
      // 不能立刻掉头
      if (body.length > 1) {
        var neck = body[1];
        cands = cands.filter(function (c) {
          return !(h.x + c.d.x === neck.x && h.y + c.d.y === neck.y);
        });
      }
      var free = cands.filter(function (c) { return !blocked(h.x + c.d.x, h.y + c.d.y); });
      if (!free.length) return null;
      // 优先朝食物走（贪心），否则选离墙最远的
      free.sort(function (a, b) {
        var da = Math.abs(h.x + a.d.x - food.x) + Math.abs(h.y + a.d.y - food.y);
        var db = Math.abs(h.x + b.d.x - food.x) + Math.abs(h.y + b.d.y - food.y);
        return da - db;
      });
      return free[0].d;
    }

    function step() {
      if (dead) return;
      var nd = chooseDir();
      if (!nd) { dead = true; return; }
      dir = nd;
      var head = { x: body[0].x + dir.x, y: body[0].y + dir.y };
      if (blocked(head.x, head.y)) { dead = true; return; }
      body.unshift(head);
      if (head.x === food.x && head.y === food.y) {
        score += 10;
        var sc = document.getElementById('snake-sc');
        if (sc) sc.textContent = score;
        if (score > snakeBest) { snakeBest = score; var bb = document.getElementById('snake-best'); if (bb) bb.textContent = snakeBest; }
        rndFood();
        if (speed > 70) speed -= 4;
      } else {
        body.pop();
      }
      draw();
    }

    function draw() {
      ctx.fillStyle = '#071a2e';
      ctx.fillRect(0, 0, cv.width, cv.height);
      ctx.strokeStyle = 'rgba(120,200,255,.10)';
      for (var i = 1; i < N; i++) {
        ctx.beginPath(); ctx.moveTo(i * cell, 0); ctx.lineTo(i * cell, cv.height); ctx.stroke();
        ctx.beginPath(); ctx.moveTo(0, i * cell); ctx.lineTo(cv.width, i * cell); ctx.stroke();
      }
      ctx.fillStyle = '#ffd479';
      ctx.shadowColor = 'rgba(255,212,121,.9)';
      ctx.shadowBlur = 14;
      ctx.beginPath();
      ctx.arc(food.x * cell + cell / 2, food.y * cell + cell / 2, cell * 0.34, 0, Math.PI * 2);
      ctx.fill();
      ctx.shadowBlur = 0;
      body.forEach(function (b, i) {
        ctx.fillStyle = i === 0 ? '#ff9ecd' : 'rgba(143,227,255,' + Math.max(0.35, 0.98 - i * 0.03) + ')';
        if (i === 0) { ctx.shadowColor = 'rgba(255,158,205,.95)'; ctx.shadowBlur = 12; }
        var pad = i === 0 ? 1 : 2;
        ctx.beginPath();
        var r = 6;
        var x = b.x * cell + pad, y = b.y * cell + pad, w = cell - pad * 2, h = cell - pad * 2;
        ctx.moveTo(x + r, y);
        ctx.arcTo(x + w, y, x + w, y + h, r);
        ctx.arcTo(x + w, y + h, x, y + h, r);
        ctx.arcTo(x, y + h, x, y, r);
        ctx.arcTo(x, y, x + w, y, r);
        ctx.fill();
        ctx.shadowBlur = 0;
      });
      if (dead) {
        ctx.fillStyle = 'rgba(4,14,28,.72)';
        ctx.fillRect(0, 0, cv.width, cv.height);
        ctx.fillStyle = '#ffd479';
        ctx.font = 'bold 42px "Microsoft YaHei",sans-serif';
        ctx.textAlign = 'center';
        ctx.fillText('撞墙了 · 得分 ' + score, cv.width / 2, cv.height / 2);
      }
    }

    function loop(now) {
      if (current !== '看她玩 · 贪吃蛇') return;
      if (!document.getElementById('snake-cv')) return;
      if (now - last > speed) { last = now; step(); }
      requestAnimationFrame(loop);
    }
    draw();
    requestAnimationFrame(loop);
  }

  /* ───────────── ③ 草稿画 ───────────── */
  function doodleOpen(subject) {
    subject = (subject || '小猫').slice(0, 12);
    open('草稿本 · ' + subject, '她拿笔随手勾两下', '发弹幕「画个 小猫」就能点题', 26);
    elBody.innerHTML =
      '<div class="gb-paper"><div class="gb-loading">正在勾线<span class="dot">…</span></div>' +
      '<img id="doodle-img" alt=""></div>';
    play('paint', 24);
    var url = PAINT_API + '/doodle?subject=' + encodeURIComponent(subject) + '&announce=1';
    fetch(url, { cache: 'no-store' })
      .then(function (r) { return r.json(); })
      .then(function (d) {
        if (!d || !d.ok) { throw new Error((d && d.error) || 'fail'); }
        var img = document.getElementById('doodle-img');
        if (!img) return;
        img.onload = function () {
          var ld = elBody.querySelector('.gb-loading');
          if (ld) ld.remove();
          img.classList.add('in');
        };
        img.src = 'http://127.0.0.1:12345/Live2D/assets/doodle/' + encodeURIComponent(d.data.file);
        elSub.textContent = '大章鱼画的 · ' + subject + ' · 用时 ' + d.data.seconds + ' 秒';
        elHint.textContent = '画得不像也别打我';
        resetBar(16);
      })
      .catch(function (e) {
        elBody.innerHTML = '<div class="gb-end">笔没水了，等会儿再画…</div>';
        elHint.textContent = String(e.message || e);
        closeLater(4000);
      });
  }

  /* ───────────── ④ 你画我猜 ───────────── */
  var PICK_WORDS = [
    { w: '小猫', a: ['猫', '小猫', '猫咪'] },
    { w: '苹果', a: ['苹果'] },
    { w: '太阳', a: ['太阳', '日头'] },
    { w: '雨伞', a: ['雨伞', '伞'] },
    { w: '章鱼', a: ['章鱼', '八爪鱼'] },
    { w: '月亮', a: ['月亮', '月牙', '明月'] },
    { w: '蛋糕', a: ['蛋糕'] },
    { w: '自行车', a: ['自行车', '单车', '脚踏车'] },
    { w: '眼镜', a: ['眼镜'] },
    { w: '小鱼', a: ['鱼', '小鱼'] },
    { w: '小花', a: ['花', '小花', '花朵'] },
    { w: '小房子', a: ['房子', '小屋', '屋子'] },
    { w: '冰淇淋', a: ['冰淇淋', '冰激凌', '雪糕'] },
    { w: '飞机', a: ['飞机'] },
    { w: '气球', a: ['气球'] },
    { w: '水杯', a: ['杯子', '水杯', '茶杯'] },
    { w: '星星', a: ['星星'] },
    { w: '蘑菇', a: ['蘑菇', '菇'] }
  ];
  var PICK = { word: '', aliases: [], done: false, timer: null };

  function pickOpen() {
    var item = PICK_WORDS[Math.floor(Math.random() * PICK_WORDS.length)];
    PICK = { word: item.w, aliases: item.a, done: false, timer: null };
    open('你画我猜', '她画，你们猜', '在弹幕里打出你猜的东西，猜中喊停', 100);
    elBody.innerHTML =
      '<div class="gb-pick"><div class="gb-loading">画笔蘸好了<span class="dot">…</span></div>' +
      '<img id="pick-img" alt=""></div>';
    play('paint', 60);
    say('我画个东西，你们猜猜是什么，猜到就直接打弹幕里。');
    var url = PAINT_API + '/doodle?subject=' + encodeURIComponent(item.w) + '&announce=0';
    var tries = 0;
    function fetchDoodle() {
      tries += 1;
      fetch(url, { cache: 'no-store' })
        .then(function (r) { return r.json(); })
        .then(function (d) {
          if (!d || !d.ok) throw new Error((d && d.error) || 'gen fail');
          var img = document.getElementById('pick-img');
          if (!img) return;
          img.onload = function () {
            var ld = elBody.querySelector('.gb-loading');
            if (ld) ld.remove();
            img.classList.add('in');
            elHint.textContent = '我画得有点抽象，凑合猜';
          };
          img.src = 'http://127.0.0.1:12345/Live2D/assets/doodle/' + encodeURIComponent(d.data.file);
        })
        .catch(function (e) {
          console.warn('[你画我猜] 画图失败 第' + tries + '次：' + (e && e.message ? e.message : e));
          if (tries < 3) { setTimeout(fetchDoodle, 2500); return; }
          if (current && current.indexOf('你画我猜') === 0) {
            elBody.innerHTML = '<div class="gb-end">画笔没水了，等会儿再画…</div>';
            closeLater(3000);
          }
        });
    }
    fetchDoodle();
    // 到点没猜中就把答案亮出来
    PICK.timer = setTimeout(function () {
      if (!PICK.done && current && current.indexOf('你画我猜') === 0) pickReveal('没人猜出来，我画的是');
    }, 92000);
  }

  function pickReveal(prefix) {
    if (PICK.done) return;
    PICK.done = true;
    clearTimeout(PICK.timer);
    elSub.textContent = prefix + '「' + PICK.word + '」';
    elHint.textContent = '再来一局发「你画我猜」';
    elBody.insertAdjacentHTML('beforeend',
      '<div class="gb-msg">答案：<b>' + PICK.word + '</b></div>');
    resetBar(6);
  }

  function pickGuess(user, t) {
    if (!PICK.word || PICK.done) return true;
    var s = String(t).replace(/\s+/g, '').toLowerCase();
    if (!s || s.length > 12) return true;
    for (var i = 0; i < PICK.aliases.length; i++) {
      if (s.indexOf(String(PICK.aliases[i]).toLowerCase()) >= 0) {
        PICK.done = true;
        clearTimeout(PICK.timer);
        elSub.textContent = '猜中了！' + user;
        elHint.textContent = '答案是「' + PICK.word + '」';
        elBody.insertAdjacentHTML('beforeend',
          '<div class="gb-msg">🎉 <b>' + user + '</b> 猜对了：' + PICK.word + '</div>');
        say('猜对了，就是' + PICK.word + '，' + user + '好眼力。');
        resetBar(5);
        return true;
      }
    }
    return true;
  }

  /* ───────────── ⑤ 历史知识快答 ───────────── */
  var QUIZ = [
    { q: '中国历史上第一个统一的中央集权王朝是？', o: ['夏朝', '秦朝', '汉朝'], a: 1, t: '公元前 221 年秦始皇统一六国' },
    { q: '「贞观之治」出现在哪位皇帝在位期间？', o: ['唐太宗', '汉武帝', '宋太祖'], a: 0, t: '唐太宗李世民' },
    { q: '改进造纸术的是谁？', o: ['张衡', '蔡伦', '毕昇'], a: 1, t: '东汉蔡伦' },
    { q: '丝绸之路的开通与谁出使西域有关？', o: ['张骞', '郑和', '玄奘'], a: 0, t: '西汉张骞' },
    { q: '明朝七下西洋的航海家是谁？', o: ['郑和', '戚继光', '徐霞客'], a: 0, t: '郑和' },
    { q: '《史记》的作者是谁？', o: ['班固', '司马迁', '司马光'], a: 1, t: '司马迁' },
    { q: '科举制正式创立于哪个朝代？', o: ['隋朝', '唐朝', '宋朝'], a: 0, t: '隋炀帝设进士科' },
    { q: '「文景之治」是哪个朝代的盛世？', o: ['西汉', '东汉', '唐朝'], a: 0, t: '汉文帝、汉景帝' },
    { q: '活字印刷术的发明者是谁？', o: ['蔡伦', '毕昇', '沈括'], a: 1, t: '北宋毕昇' },
    { q: '甲午中日战争后签订的条约是？', o: ['《南京条约》', '《马关条约》', '《辛丑条约》'], a: 1, t: '1895 年《马关条约》' },
    { q: '中华人民共和国成立于哪一年？', o: ['1945 年', '1949 年', '1950 年'], a: 1, t: '1949 年 10 月 1 日' },
    { q: '都江堰水利工程由谁主持修建？', o: ['李冰', '大禹', '郑国'], a: 0, t: '战国秦昭王时期李冰' },
    { q: '「安史之乱」发生在哪个朝代？', o: ['汉朝', '唐朝', '宋朝'], a: 1, t: '唐玄宗天宝年间' },
    { q: '四大发明中用于航海定向的是？', o: ['造纸术', '指南针', '火药'], a: 1, t: '指南针' },
    { q: '元朝的建立者是谁？', o: ['成吉思汗', '忽必烈', '努尔哈赤'], a: 1, t: '忽必烈' },
    { q: '「靖康之变」导致哪个朝代灭亡？', o: ['北宋', '南宋', '唐朝'], a: 0, t: '1127 年北宋灭亡' },
    { q: '世界上最早的纸币「交子」出现在？', o: ['唐朝', '北宋', '元朝'], a: 1, t: '北宋四川' },
    { q: '屈原生活在哪个时期？', o: ['春秋', '战国', '汉朝'], a: 1, t: '战国时期楚国' },
    { q: '「卧薪尝胆」说的是哪位国君？', o: ['吴王夫差', '越王勾践', '齐桓公'], a: 1, t: '越王勾践' },
    { q: '《资治通鉴》的主编是谁？', o: ['司马迁', '司马光', '班固'], a: 1, t: '编年体通史，从战国一直写到五代' },
    { q: '郑成功收复台湾是在哪个时期？', o: ['明朝末年', '清朝初年', '元朝'], a: 0, t: '1661 年，明末清初' },
    { q: '「五四运动」发生在哪一年？', o: ['1911 年', '1919 年', '1927 年'], a: 1, t: '1919 年' }
  ];
  var QZ = { idx: -1, done: false, winner: '', timer: null, lock: false };

  function quizOpen() {
    var i = Math.floor(Math.random() * QUIZ.length);
    QZ = { idx: i, done: false, winner: '', timer: null, lock: false };
    var q = QUIZ[i];
    open('历史知识快答', '第 ' + (i + 1) + ' 题', '弹幕发 A / B / C 作答，第一个答对的算', 30);
    elBody.innerHTML =
      '<div class="gb-quiz"><div class="gb-q">' + q.q + '</div>' +
      '<div class="gb-opts">' + q.o.map(function (x, k) {
        return '<div class="gb-opt" data-k="' + k + '"><b>' + 'ABC'[k] + '</b>' + x + '</div>';
      }).join('') + '</div><div class="gb-msg" id="qz-msg"></div></div>';
    play('count', 4);
    say('来道历史题：' + q.q + '。A，' + q.o[0] + '；B，' + q.o[1] + '；C，' + q.o[2] + '。想好了发字母。');
    QZ.timer = setTimeout(function () {
      if (!QZ.done && current && current.indexOf('历史知识快答') === 0) quizReveal('');
    }, 26000);
  }

  function quizReveal(prefix) {
    if (QZ.done) return;
    QZ.done = true;
    clearTimeout(QZ.timer);
    var q = QUIZ[QZ.idx] || QUIZ[0];
    var opts = elBody.querySelectorAll('.gb-opt');
    for (var k = 0; k < opts.length; k++) {
      if (k === q.a) opts[k].classList.add('hit');
      else opts[k].classList.add('miss');
    }
    var msg = elBody.querySelector('#qz-msg');
    if (msg) msg.innerHTML = prefix + '答案 <b>' + 'ABC'[q.a] + '</b>：' + q.o[q.a] + '（' + q.t + '）';
    elHint.textContent = '再来一题发「历史快答」';
    resetBar(7);
  }

  function quizAnswer(user, t) {
    if (!QUIZ[QZ.idx] || QZ.done) return true;
    var s = String(t).trim().toUpperCase();
    var k = -1;
    var m = s.match(/(?:选|答案|我选)?\s*([ABC])\b/) || s.match(/^([ABC])$/);
    if (m) k = 'ABC'.indexOf(m[1]);
    else if (/^[123]$/.test(s)) k = Number(s) - 1;
    if (k < 0) return true;                 // 不是作答，当普通弹幕
    var q = QUIZ[QZ.idx];
    if (k === q.a) {
      QZ.done = true;
      clearTimeout(QZ.timer);
      elSub.textContent = '答对了！' + user;
      elBody.querySelectorAll('.gb-opt').forEach(function (el, i2) {
        el.classList.add(i2 === q.a ? 'hit' : 'miss');
      });
      var msg = elBody.querySelector('#qz-msg');
      if (msg) msg.innerHTML = '🎉 <b>' + user + '</b> 抢答正确：' + 'ABC'[q.a] + ' · ' + q.o[q.a];
      say('答对了，' + user + '。正确答案是' + 'ABC'[q.a] + '，' + q.o[q.a] + '，' + q.t + '。');
      resetBar(6);
    } else if (!QZ.lock) {
      QZ.lock = true;                        // 只提示一次，别刷屏
      var m2 = elBody.querySelector('#qz-msg');
      if (m2) m2.innerHTML = user + ' 选了 ' + 'ABC'[k] + '，不对哦，再想想';
      setTimeout(function () { QZ.lock = false; }, 2500);
    }
    return true;
  }

  /* ───────────── 命令解析 ───────────── */
  var RE_RPS = /猜拳|石头剪刀布|剪刀石头布|玩一把|来一局/;
  var RE_SNAKE = /贪吃蛇|玩个小游戏|表演个游戏|打把游戏|打游戏/;
  var RE_PICK = /你画我猜|你画个我猜|画画猜|猜猜我画/;
  var RE_QUIZ = /历史快答|历史知识快答|快问快答|历史题|考考我|出个题/;
  var RE_DOODLE = /画个\s*(.{1,12})|画一下\s*(.{1,12})|随便画个\s*(.{1,12})|草稿\s*(.{1,12})/;

  function handle(text, user) {
    if (!text) return false;
    var t = String(text).trim();

    // 你画我猜进行中：只认猜词
    if (current === '你画我猜') {
      pickGuess(user || '观众', t);
      return true;
    }
    // 历史快答进行中：只认 A/B/C
    if (current === '历史知识快答') {
      quizAnswer(user || '观众', t);
      return true;
    }

    // 猜拳进行中：只认出拳
    if (current === '猜拳 · 第 1 局' || (current && current.indexOf('猜拳') === 0)) {
      if (RPS.waiting) {
        if (/石头|^石$|✊/.test(t)) { rpsPlay('石头'); return true; }
        if (/剪刀|^剪$|✌/.test(t)) { rpsPlay('剪刀'); return true; }
        if (/^布$|布[!！。.]?$|✋/.test(t)) { rpsPlay('布'); return true; }
      }
      return true;   // 猜拳期间别让别的动作抢
    }

    if (RE_RPS.test(t)) {
      if (current) return false;
      rpsOpen();
      return true;
    }
    if (RE_PICK.test(t)) {
      if (current) return false;
      pickOpen();
      return true;
    }
    if (RE_QUIZ.test(t)) {
      if (current) return false;
      quizOpen();
      return true;
    }
    if (RE_SNAKE.test(t)) {
      if (current) return false;
      snakeOpen();
      return true;
    }
    var m = t.match(RE_DOODLE);
    if (m) {
      if (current) return false;
      var subject = (m[1] || m[2] || m[3] || m[4] || '').trim();
      subject = subject.replace(/[，。,.\s]+$/, '');
      if (!subject) subject = '小猫';
      doodleOpen(subject);
      return true;
    }
    return false;
  }

  window.__gameHandle = handle;
  window.__gameState = function () {
    return {
      current: current,
      rps: RPS.win + '-' + RPS.lose + '-' + RPS.draw,
      pick: { word: PICK.word, done: !!PICK.done },
      quiz: { idx: QZ.idx, done: !!QZ.done, winner: QZ.winner }
    };
  };
  window.__gameClose = close;

  /* 直接挂到弹幕广播（8888 支持多客户端） */
  var retry = 0;
  function connect() {
    var ws;
    try { ws = new WebSocket('ws://127.0.0.1:8888'); } catch (e) { return; }
    ws.onopen = function () { retry = 0; console.log('[game] 弹幕已连接'); };
    ws.onmessage = function (e) {
      try {
        var m = JSON.parse(e.data);
        if (String(m.Type) !== '1') return;
        var d = JSON.parse(m.Data || '{}');
        handle(d && d.Content, d && d.User && d.User.Nickname);
      } catch (_) {}
    };
    ws.onclose = function () {
      retry = Math.min(retry + 1, 6);
      setTimeout(connect, 2000 * retry);
    };
  }
  connect();
})();
