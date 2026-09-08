/* 流程引擎示例 前端逻辑 */
let currentUser = null;
const users = [];
let lastGraphKey = null;
let editingTask = null; // 驳回重提: 正在修改的待办任务

/* ---------- 工具 ---------- */
async function api(url, options) {
    const resp = await fetch(url, options);
    return resp.json();
}

function toast(msg, ok = true) {
    const el = document.getElementById('toast');
    el.textContent = msg;
    el.className = 'show ' + (ok ? 'ok' : 'err');
    setTimeout(() => el.className = '', 2500);
}

function fmtTime(t) {
    if (!t) return '-';
    return String(t).replace('T', ' ').slice(0, 19);
}

function escapeHtml(s) {
    return String(s == null ? '' : s)
        .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;').replace(/'/g, '&#39;');
}

function userName(id) {
    const u = users.find(x => x.id === id);
    return u ? `${u.name} (${u.id})` : (id || '');
}

/* 日志字段: opr_ifo 可能是框架 Base64 编码, 也可能是后端已解码的明文, 统一转中文 */
function decodeOprIfo(b64) {
    if (!b64) return '';
    // 已含中文的明文(后端已解码)直接返回
    if (/[\u4e00-\u9fa5]/.test(b64)) return b64;
    try {
        const bytes = Uint8Array.from(atob(b64), c => c.charCodeAt(0));
        return new TextDecoder('utf-8').decode(bytes);
    } catch (e) {
        return b64; // 非 Base64 时原样返回
    }
}

/* 日志字段: 操作类型转中文 */
function oprTypText(t) {
    return ({ Start: '发起', Submit: '提交', Approve: '审批' })[t] || t || '-';
}

/* 日志字段: 审批结果转中文 */
function oprRetText(r) {
    if (r === 'true') return '通过';
    if (r === 'false') return '驳回';
    return r || '-';
}

/* ---------- 用户 ---------- */
async function loadUsers() {
    const res = await api('/api/users');
    users.push(...res.data);
    const sel = document.getElementById('userSelect');
    sel.innerHTML = '';
    for (const u of users) {
        const opt = document.createElement('option');
        opt.value = u.id;
        opt.textContent = `${u.id} ${u.name} (${u.title})`;
        sel.appendChild(opt);
    }
    currentUser = users[0];
    sel.value = currentUser.id;
    sel.onchange = () => {
        currentUser = users.find(u => u.id === sel.value);
        loadTodos();
    };
}

/* ---------- 发起 ---------- */
async function startProcess() {
    const flowType = document.getElementById('flowType').value;
    if (flowType === 'employee') {
        await startEmployeeProcess();
        return;
    }
    if (flowType === 'expense') {
        await startExpenseProcess();
        return;
    }
    const reason = document.getElementById('reason').value.trim();
    const days = parseInt(document.getElementById('days').value, 10) || 1;
    if (!reason) { toast('请填写请假事由', false); return; }
    let res;
    if (editingTask) {
        // 驳回重提: 更新表单内容并重新提交
        res = await api('/api/approve', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                userId: currentUser.id,
                mstrleId: currentUser.role,
                processDefinitionKey: editingTask.processDefinitionKey,
                businessKey: editingTask.businessKey,
                taskName: editingTask.taskName,
                approved: true,
                comment: '修改后重新提交',
                variables: { reason, days }
            })
        });
    } else {
        res = await api('/api/start', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ userId: currentUser.id, reason, days })
        });
    }
    document.getElementById('startResult').textContent = res.message || '';
    if (res.success) {
        toast(editingTask ? '修改已重新提交: ' + editingTask.businessKey : '发起成功: ' + res.businessKey);
        editingTask = null;
        document.getElementById('reason').value = '';
        document.getElementById('days').value = 1;
        loadTodos();
    } else {
        toast(res.message, false);
    }
}

/* 发起员工申请 (请假/硬件申领) */
async function startEmployeeProcess() {
    const reason = document.getElementById('eaReason').value.trim();
    if (!reason) { toast('请填写申请事由', false); return; }
    const payload = {
        userId: currentUser.id,
        applyType: document.getElementById('eaApplyType').value,
        reason,
        detail: document.getElementById('eaDetail').value.trim(),
        needManager: document.getElementById('eaNeedManager').value === 'true'
    };
    let res;
    if (editingTask) {
        // 驳回重提: 更新表单内容并重新提交
        res = await api('/api/approve', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                userId: currentUser.id,
                mstrleId: currentUser.role,
                processDefinitionKey: editingTask.processDefinitionKey,
                businessKey: editingTask.businessKey,
                taskName: editingTask.taskName,
                approved: true,
                comment: '修改后重新提交',
                variables: payload
            })
        });
    } else {
        res = await api('/api/start/employee', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload)
        });
    }
    document.getElementById('startResult').textContent = res.message || '';
    if (res.success) {
        toast(editingTask ? '修改已重新提交: ' + editingTask.businessKey : '发起成功: ' + res.businessKey);
        editingTask = null;
        document.getElementById('eaReason').value = '';
        document.getElementById('eaDetail').value = '';
        loadTodos();
    } else {
        toast(res.message, false);
    }
}

/* 发起报销 (金额/事由/说明) */
async function startExpenseProcess() {
    const amount = parseFloat(document.getElementById('exAmount').value) || 0;
    const reason = document.getElementById('exReason').value.trim();
    if (!reason) { toast('请填写报销事由', false); return; }
    if (amount <= 0) { toast('请填写正确的报销金额', false); return; }
    const payload = {
        userId: currentUser.id,
        amount,
        reason,
        detail: document.getElementById('exDetail').value.trim()
    };
    let res;
    if (editingTask) {
        // 驳回重提: 更新表单内容并重新提交
        res = await api('/api/approve', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                userId: currentUser.id,
                mstrleId: currentUser.role,
                processDefinitionKey: editingTask.processDefinitionKey,
                businessKey: editingTask.businessKey,
                taskName: editingTask.taskName,
                approved: true,
                comment: '修改后重新提交',
                variables: payload
            })
        });
    } else {
        res = await api('/api/start/expense', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload)
        });
    }
    document.getElementById('startResult').textContent = res.message || '';
    if (res.success) {
        toast(editingTask ? '修改已重新提交: ' + editingTask.businessKey : '发起成功: ' + res.businessKey);
        editingTask = null;
        document.getElementById('exReason').value = '';
        document.getElementById('exDetail').value = '';
        loadTodos();
    } else {
        toast(res.message, false);
    }
}

/* 驳回重提: 重新载入申请表单, 供修改后重新提交 */
function editTask(item) {
    const v = item.variables || {};
    const key = item.processDefinitionKey;
    const isEmployee = key === 'proc_employee_apply';
    const isExpense = key === 'expense';
    switchTab('start');
    document.getElementById('flowType').value = isEmployee ? 'employee' : (isExpense ? 'expense' : 'leave');
    toggleFlowForm();
    if (isEmployee) {
        document.getElementById('eaApplyType').value = v.applyType || 'leave';
        document.getElementById('eaReason').value = v.reason || '';
        document.getElementById('eaDetail').value = v.detail || '';
        document.getElementById('eaNeedManager').value = (v.needManager === true || v.needManager === 'true') ? 'true' : 'false';
    } else if (isExpense) {
        document.getElementById('exAmount').value = v.amount || 1000;
        document.getElementById('exReason').value = v.reason || '';
        document.getElementById('exDetail').value = v.detail || '';
    } else {
        document.getElementById('reason').value = v.reason || '';
        document.getElementById('days').value = v.days || 1;
    }
    editingTask = {
        processDefinitionKey: item.processDefinitionKey,
        businessKey: item.businessKey,
        taskName: item.taskName
    };
    document.getElementById('startResult').textContent = `正在修改申请 [${item.businessKey}], 修改后点击"提交申请"重新提交`;
    toast('已载入申请内容, 请修改后重新提交');
}

/* 切换发起表单 (请假 / 员工申请 / 报销) */
function toggleFlowForm() {
    const type = document.getElementById('flowType').value;
    document.getElementById('leaveForm').style.display = type === 'leave' ? '' : 'none';
    document.getElementById('employeeForm').style.display = type === 'employee' ? '' : 'none';
    document.getElementById('expenseForm').style.display = type === 'expense' ? '' : 'none';
}

/* ---------- 待办 ---------- */
async function loadTodos() {
    const res = await api(`/api/todos?userId=${currentUser.id}&mstrleId=${currentUser.role}`);
    const box = document.getElementById('todoList');
    box.innerHTML = '';
    if (!res.success) { toast(res.message, false); return; }
    if (!res.data.length) {
        box.innerHTML = '<div class="empty">暂无待办任务</div>';
        return;
    }
    for (const item of res.data) {
        const card = document.createElement('div');
        card.className = 'todo-card';
        const isModify = !!item.isModifyTask;
        card.innerHTML = `
            <div class="todo-head">
                <span class="flow-name">${item.processDefinitionName}</span>
                <span class="badge ${isModify ? 'reject' : ''}">${item.taskName || ''}</span>
            </div>
            <div class="todo-meta">
                <span>业务号: <b>${item.businessKey}</b></span>
                <span>发起: ${fmtTime(item.processStartTime)}</span>
                <span>到达: ${fmtTime(item.taskCreateTime)}</span>
            </div>
            <div class="todo-actions">
                <input class="comment" placeholder="审批意见(可选)">
                ${isModify
                    ? `<button class="btn primary" data-edit="${item.businessKey}">修改并重新提交</button>`
                    : `<button class="btn pass" data-key="${item.processDefinitionKey}" data-bk="${item.businessKey}" data-task="${item.taskName}" data-approved="true">通过</button>
                       <button class="btn reject" data-key="${item.processDefinitionKey}" data-bk="${item.businessKey}" data-task="${item.taskName}" data-approved="false">驳回</button>`}
                <button class="btn ghost" data-view="${item.businessKey}">查看流程</button>
            </div>`;
        card.querySelectorAll('button[data-approved]').forEach(btn => {
            btn.onclick = () => approve(
                btn.dataset.key, btn.dataset.bk, btn.dataset.task,
                btn.dataset.approved === 'true',
                card.querySelector('.comment').value);
        });

        const editBtn = card.querySelector('button[data-edit]');
        if (editBtn) editBtn.onclick = () => editTask(item);

        const viewBtn = card.querySelector('button[data-view]');
        if (viewBtn) viewBtn.onclick = () => viewGraph(item.businessKey);
        box.appendChild(card);
    }
}

/* ---------- 审批 ---------- */
async function approve(processDefinitionKey, businessKey, taskName, approved, comment) {
    const res = await api('/api/approve', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
            userId: currentUser.id,
            mstrleId: currentUser.role,
            processDefinitionKey, businessKey, taskName, approved, comment
        })
    });
    toast(res.message || '操作完成', res.success);
    loadTodos();
}


/* ---------- 我发起的 ---------- */
async function loadMine() {
    const res = await api(`/api/mine?userId=${currentUser.id}`);
    const body = document.getElementById('mineBody');
    body.innerHTML = '';
    if (!res.success) { toast(res.message, false); return; }
    if (!res.data.length) {
        body.innerHTML = '<tr><td colspan="6" class="empty">暂无发起的流程</td></tr>';
        return;
    }
    for (const it of res.data) {
        const tr = document.createElement('tr');
        tr.innerHTML = `
            <td>${it.businessKey}</td>
            <td>${it.processDefinitionName}</td>
            <td><span class="badge ${it.state === '进行中' ? 'run' : 'done'}">${it.state}</span></td>
            <td>${fmtTime(it.startTime)}</td>
            <td>${fmtTime(it.endTime)}</td>
            <td><button class="btn ghost" data-bk="${it.businessKey}">全景</button></td>`;
        tr.querySelector('button').onclick = () => viewGraph(it.businessKey);
        body.appendChild(tr);
    }
}

/* ---------- 日志 ---------- */
async function loadLogs() {
    const res = await api('/api/logs');
    const body = document.getElementById('logsBody');
    body.innerHTML = '';
    if (!res.success) { toast(res.message, false); return; }
    if (!res.data.length) {
        body.innerHTML = '<tr><td colspan="7" class="empty">暂无日志</td></tr>';
        return;
    }
    for (const it of res.data) {
        const tr = document.createElement('tr');
        tr.innerHTML = `
            <td>${fmtTime(it.tsm)}</td>
            <td>${it.bus_kid}</td>
            <td>${it.tsk_nme || '-'}</td>
            <td>${escapeHtml(userName(it.opr))}</td>
            <td>${oprTypText(it.opr_typ)}</td>
            <td>${oprRetText(it.opr_ret)}</td>
            <td>${escapeHtml(decodeOprIfo(it.opr_ifo) || '-')}</td>`;
        body.appendChild(tr);
    }
}

/* ---------- 流程全景 ---------- */
function viewGraph(businessKey) {
    switchTab('graph');
    if (lastGraphKey !== businessKey) loadGraph(businessKey);
}

async function loadGraph(businessKey) {
    if (!businessKey) { toast('请先输入业务号', false); return; }
    lastGraphKey = businessKey;
    document.getElementById('bkInput').value = businessKey;
    const res = await api('/api/process/detail?businessKey=' + encodeURIComponent(businessKey));
    if (!res.success) {
        document.getElementById('graphInfo').innerHTML = '';
        document.getElementById('graphSvg').innerHTML = '';
        document.getElementById('graphTimeline').innerHTML = '';
        document.getElementById('graphLogs').innerHTML = '';
        toast(res.message, false);
        return;
    }
    const data = res.data;
    renderGraphInfo(data);
    renderGraphSvg(data.graph);
    renderGraphTimeline(data.activities || []);
    renderGraphLogs(data.logs || []);
}

/* 顶部信息卡 */
function renderGraphInfo(data) {
    const el = document.getElementById('graphInfo');
    const vars = data.variables || {};
    const cur = data.currentTasks || [];
    const isRunning = data.state === '进行中';
    const curTxt = cur.length
        ? cur.map(t => `<b>${escapeHtml(t.taskName)}</b> <span class="dim">(${fmtTime(t.taskCreateTime)})</span>`).join('、')
        : (isRunning ? '<span class="dim">无活跃任务</span>' : '<span class="dim">流程已结束</span>');

    let approvedTxt = '-';
    if (vars.approved === true) approvedTxt = '<span class="badge done">通过</span>';
    else if (vars.approved === false) approvedTxt = '<span class="badge reject">驳回</span>';

    el.innerHTML = `
        <div class="info-grid">
            <div class="info-item"><span class="k">业务号</span><span class="v">${escapeHtml(data.businessKey)}</span></div>
            <div class="info-item"><span class="k">流程名称</span><span class="v">${escapeHtml(data.processDefinitionName)}</span></div>
            <div class="info-item"><span class="k">状态</span><span class="v">${isRunning ? '<span class="badge run">进行中</span>' : '<span class="badge done">已结束</span>'}</span></div>
            <div class="info-item"><span class="k">发起人</span><span class="v">${escapeHtml(userName(data.startUserId))}</span></div>
            <div class="info-item"><span class="k">发起时间</span><span class="v">${fmtTime(data.startTime)}</span></div>
            <div class="info-item"><span class="k">结束时间</span><span class="v">${fmtTime(data.endTime)}</span></div>
            <div class="info-item"><span class="k">当前节点</span><span class="v">${curTxt}</span></div>
            <div class="info-item"><span class="k">请假事由</span><span class="v">${escapeHtml(vars.reason) || '-'}</span></div>
            <div class="info-item"><span class="k">请假天数</span><span class="v">${vars.days != null ? escapeHtml(vars.days) + ' 天' : '-'}</span></div>
            <div class="info-item"><span class="k">审批结果</span><span class="v">${approvedTxt}</span></div>
        </div>`;
}

/* SVG 流程图: 标准 BPMN 专业渲染 (圆角节点 / 任务图标 / 网关X / 粗线箭头) */
function renderGraphSvg(graph) {
    const box = document.getElementById('graphSvg');
    box.innerHTML = '';
    if (!graph || !graph.process || !graph.process.length) {
        box.innerHTML = '<div class="empty">暂无流程图数据</div>';
        return;
    }
    const nodes = graph.process.filter(n => n.nodeType !== 'sequenceFlow' && n.bounds);
    const edges = graph.process.filter(n => n.nodeType === 'sequenceFlow' && n.waypoints);

    let minX = Infinity, minY = Infinity, maxX = -Infinity, maxY = -Infinity;
    const addPoint = (x, y) => {
        if (x < minX) minX = x;
        if (x > maxX) maxX = x;
        if (y < minY) minY = y;
        if (y > maxY) maxY = y;
    };
    nodes.forEach(n => {
        if (n.bounds) {
            addPoint(n.bounds.x, n.bounds.y);
            addPoint(n.bounds.x + n.bounds.width, n.bounds.y + n.bounds.height);
        }
    });
    edges.forEach(e => (e.waypoints || []).forEach(w => addPoint(w.x, w.y)));
    if (minX === Infinity) {
        box.innerHTML = '<div class="empty">暂无流程图数据</div>';
        return;
    }

    const pad = 50;
    const vw = maxX - minX + pad * 2;
    const vh = maxY - minY + pad * 2;
    const px = minX - pad, py = minY - pad;

    // 统一类型(兼容大小写及 Impl 后缀)
    const typeOf = n => {
        const t = (n.nodeType || '').toString().toLowerCase().replace(/impl$/, '');
        return t;
    };

    let html = `<svg viewBox="${px} ${py} ${vw} ${vh}" width="100%" height="${Math.min(vh, 560)}" xmlns="http://www.w3.org/2000/svg">`;

    // 箭头 marker 定义
    html += `<defs>
        <marker id="arrow-idle" markerWidth="10" markerHeight="10" refX="9" refY="5" orient="auto" markerUnits="strokeWidth">
            <path d="M0,0 L10,5 L0,10 L2,5 Z" fill="#9ca3af"/>
        </marker>
        <marker id="arrow-done" markerWidth="10" markerHeight="10" refX="9" refY="5" orient="auto" markerUnits="strokeWidth">
            <path d="M0,0 L10,5 L0,10 L2,5 Z" fill="#16a34a"/>
        </marker>
        <marker id="arrow-active" markerWidth="10" markerHeight="10" refX="9" refY="5" orient="auto" markerUnits="strokeWidth">
            <path d="M0,0 L10,5 L0,10 L2,5 Z" fill="#2566eb"/>
        </marker>
    </defs>`;

    // 连线 (path + marker-end)
    edges.forEach(e => {
        const pts = e.waypoints || [];
        if (pts.length < 2) return;
        const cls = e.state === 'completed' ? 'done' : (e.state === 'active' ? 'active' : 'idle');
        let d = `M${pts[0].x},${pts[0].y}`;
        for (let i = 1; i < pts.length; i++) d += ` L${pts[i].x},${pts[i].y}`;
        html += `<path class="edge ${cls}" d="${d}" marker-end="url(#arrow-${cls})"/>`;
        if (e.name) {
            const mid = pts[Math.floor(pts.length / 2)];
            html += `<text class="edge-label" x="${mid.x}" y="${mid.y - 8}">${escapeHtml(e.name)}</text>`;
        }
    });

    // 节点
    nodes.forEach(n => {
        const b = n.bounds;
        const cx = b.x + b.width / 2, cy = b.y + b.height / 2;
        const cls = n.state === 'completed' ? 'done' : (n.state === 'active' ? 'active' : 'idle');
        const type = typeOf(n);

        if (type === 'startevent' || type === 'endevent') {
            const r = Math.min(b.width, b.height) / 2 - 1;
            const sw = type === 'endevent' ? 3.5 : 2;
            html += `<circle class="node ${cls}" cx="${cx}" cy="${cy}" r="${r}" stroke-width="${sw}"/>`;
            if (type === 'endevent') {
                html += `<circle class="node-fill" cx="${cx}" cy="${cy}" r="${r * 0.45}"/>`;
            }
            html += `<text class="node-label" x="${cx}" y="${cy + r + 16}">${escapeHtml(n.name || '')}</text>`;
        } else if (type === 'exclusivegateway') {
            const hw = b.width / 2 - 2, hh = b.height / 2 - 2;
            html += `<polygon class="node ${cls}" points="${cx},${cy - hh} ${cx + hw},${cy} ${cx},${cy + hh} ${cx - hw},${cy}"/>`;
            // 内部 X (占菱形内部约 36%, 标准 BPMN 比例)
            const m = Math.round(hw * 0.32);
            html += `<line class="gateway-x" x1="${cx - hw + m}" y1="${cy - hh + m}" x2="${cx + hw - m}" y2="${cy + hh - m}"/>`;
            html += `<line class="gateway-x" x1="${cx + hw - m}" y1="${cy - hh + m}" x2="${cx - hw + m}" y2="${cy + hh - m}"/>`;
            // 网关标签放正下方, 避免与侧向连线重叠
            html += `<text class="node-label" x="${cx}" y="${cy + hh + 16}">${escapeHtml(n.name || '')}</text>`;
        } else {
            // 任务矩形 (userTask / serviceTask / 其他)
            const rx = 4, ry = 4;
            const x = b.x + 1, y = b.y + 1, w = b.width - 2, h = b.height - 2;
            html += `<rect class="node ${cls}" x="${x}" y="${y}" width="${w}" height="${h}" rx="${rx}" ry="${ry}"/>`;

            // 图标
            if (type === 'usertask') {
                // 左上角小人图标
                const ix = x + 10, iy = y + 8;
                html += `<g transform="translate(${ix},${iy})">`;
                html += `<circle cx="6" cy="4" r="3" fill="none" class="icon-stroke"/>`;
                html += `<path d="M2,12 Q6,8 10,12" fill="none" class="icon-stroke"/>`;
                html += `</g>`;
            } else if (type === 'servicetask') {
                // 左上角齿轮图标
                const ix = x + 10, iy = y + 8;
                html += `<g transform="translate(${ix},${iy})">`;
                html += `<circle cx="6" cy="6" r="2.5" fill="none" class="icon-stroke"/>`;
                html += `<line x1="6" y1="1.5" x2="6" y2="4" class="icon-stroke"/>`;
                html += `<line x1="6" y1="8" x2="6" y2="10.5" class="icon-stroke"/>`;
                html += `<line x1="1.5" y1="6" x2="4" y2="6" class="icon-stroke"/>`;
                html += `<line x1="8" y1="6" x2="10.5" y2="6" class="icon-stroke"/>`;
                html += `</g>`;
            }

            // 文字 (有图标时稍下移)
            const hasIcon = type === 'usertask' || type === 'servicetask';
            const ty = hasIcon ? cy + 3 : cy + 4;
            html += `<text class="node-text" x="${cx}" y="${ty}">${escapeHtml(n.name || '')}</text>`;
        }
    });
    html += '</svg>';
    box.innerHTML = html;
}

/* 办理轨迹时间线 */
function renderGraphTimeline(activities) {
    const box = document.getElementById('graphTimeline');
    box.innerHTML = '';
    if (!activities.length) {
        box.innerHTML = '<div class="empty">暂无轨迹数据</div>';
        return;
    }
    const icon = {
        startEvent: '●', endEvent: '◉',
        exclusiveGateway: '◇', userTask: '▣'
    };
    for (const a of activities) {
        const item = document.createElement('div');
        item.className = 'tl-item';
        const state = a.state === 'active' ? 'active' : 'completed';
        const who = a.assignee ? `<span>办理人: <b>${escapeHtml(userName(a.assignee))}</b></span>` : '';
        const dur = (a.startTime && a.endTime) ? `<span>耗时: ${escapeHtml(timeCost(a.startTime, a.endTime))}</span>` : '';
        item.innerHTML = `
            <div class="tl-dot ${state}">${icon[a.nodeType] || '▸'}</div>
            <div class="tl-body">
                <div class="tl-head">
                    <span class="tl-name">${escapeHtml(a.activityName || a.activityId)}</span>
                    <span class="badge ${state === 'active' ? 'run' : 'done'}">${state === 'active' ? '进行中' : '已完成'}</span>
                </div>
                <div class="tl-meta">
                    ${who}
                    <span>进入: ${fmtTime(a.startTime)}</span>
                    ${a.endTime ? `<span>离开: ${fmtTime(a.endTime)}</span>` : ''}
                    ${dur}
                </div>
            </div>`;
        box.appendChild(item);
    }
}

function timeCost(start, end) {
    const s = new Date(start.replace(' ', 'T')).getTime();
    const e = new Date(end.replace(' ', 'T')).getTime();
    const diff = Math.max(0, e - s);
    const sec = Math.floor(diff / 1000);
    if (sec < 60) return sec + ' 秒';
    if (sec < 3600) return Math.floor(sec / 60) + ' 分钟';
    return (sec / 3600).toFixed(1) + ' 小时';
}

/* 该流程的操作日志 */
function renderGraphLogs(logs) {
    const body = document.getElementById('graphLogs');
    body.innerHTML = '';
    if (!logs.length) {
        body.innerHTML = '<tr><td colspan="6" class="empty">暂无日志</td></tr>';
        return;
    }
    for (const it of logs) {
        const tr = document.createElement('tr');
        tr.innerHTML = `
            <td>${fmtTime(it.tsm)}</td>
            <td>${escapeHtml(it.tsk_nme || '-')}</td>
            <td>${escapeHtml(userName(it.opr))}</td>
            <td>${oprTypText(it.opr_typ)}</td>
            <td>${oprRetText(it.opr_ret)}</td>
            <td>${escapeHtml(decodeOprIfo(it.opr_ifo) || '-')}</td>`;
        body.appendChild(tr);
    }
}

/* ---------- Tab 切换 ---------- */
function switchTab(name) {
    document.querySelectorAll('.tab').forEach(t => t.classList.toggle('active', t.dataset.tab === name));
    document.querySelectorAll('.panel').forEach(p => p.classList.toggle('active', p.id === name));
    if (name === 'todos') loadTodos();
    if (name === 'mine') loadMine();
    if (name === 'logs') loadLogs();
    if (name === 'graph' && lastGraphKey) loadGraph(lastGraphKey);
}

/* ---------- 初始化 ---------- */
window.onload = async () => {
    document.querySelectorAll('.tab').forEach(t => t.onclick = () => switchTab(t.dataset.tab));
    document.getElementById('startBtn').onclick = startProcess;
    document.getElementById('refreshTodos').onclick = loadTodos;
    document.getElementById('refreshMine').onclick = loadMine;
    document.getElementById('refreshLogs').onclick = loadLogs;
    document.getElementById('bkSearch').onclick = () => loadGraph(document.getElementById('bkInput').value.trim());
    document.getElementById('bkInput').addEventListener('keydown', e => {
        if (e.key === 'Enter') loadGraph(document.getElementById('bkInput').value.trim());
    });
    document.getElementById('refreshGraph').onclick = () => loadGraph(lastGraphKey);
    await loadUsers();
    loadTodos();
};
