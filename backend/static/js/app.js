document.addEventListener('DOMContentLoaded', () => {
    // Global Audio Object
    const faustAudio = new Audio();
    // Settings
    const speakerSelect = document.getElementById('speaker-select');
    const volumeSlider = document.getElementById('volume-slider');
    if (speakerSelect) speakerSelect.value = localStorage.getItem('speaker_id') || '47';
    if (volumeSlider) volumeSlider.value = localStorage.getItem('faust_volume') || '0.5';
    faustAudio.volume = volumeSlider ? parseFloat(volumeSlider.value) : 0.5;

    const saveSettingsBtn = document.getElementById('save-settings-btn');
    const speakerSelect = document.getElementById('speaker-select');
    const personalitySelect = document.getElementById('personality-select');
    const volumeSlider = document.getElementById('volume-slider');

    // 起動時に性格一覧を取得
    async function loadPersonalities() {
        try {
            const res = await fetch('/api/study_coaching_hub', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({ phase: 'get_personalities' })
            });
            const data = await res.json();
            if (data.status === 'success' && personalitySelect) {
                personalitySelect.innerHTML = '';
                data.personalities.forEach((p, idx) => {
                    const opt = document.createElement('option');
                    opt.value = p.prompt;
                    opt.textContent = p.name;
                    opt.dataset.voice = p.voice_id;
                    personalitySelect.appendChild(opt);
                });
                
                // 復元
                const savedPrompt = localStorage.getItem('system_prompt');
                if (savedPrompt) {
                    personalitySelect.value = savedPrompt;
                } else if (personalitySelect.options.length > 0) {
                    personalitySelect.selectedIndex = 0;
                    localStorage.setItem('system_prompt', personalitySelect.value);
                }
            }
        } catch (e) {
            console.error('Failed to load personalities', e);
        }
    }
    loadPersonalities();

    if (personalitySelect) {
        personalitySelect.addEventListener('change', (e) => {
            const selectedOpt = e.target.options[e.target.selectedIndex];
            localStorage.setItem('system_prompt', selectedOpt.value);
            if (speakerSelect && selectedOpt.dataset.voice) {
                speakerSelect.value = selectedOpt.dataset.voice;
                localStorage.setItem('speaker_id', selectedOpt.dataset.voice);
            }
        });
    }

    if (saveSettingsBtn) {
        saveSettingsBtn.addEventListener('click', () => {
            if (personalitySelect) {
                localStorage.setItem('system_prompt', personalitySelect.value);
            }
            if (speakerSelect) {
                localStorage.setItem('speaker_id', speakerSelect.value);
            }
            if (volumeSlider) {
                localStorage.setItem('faust_volume', volumeSlider.value);
                faustAudio.volume = parseFloat(volumeSlider.value);
            }
            alert('設定を保存しました。');
        });
    }

    // --- Quill.js Initialization ---
    let memoEditor;
    if (document.getElementById('memo-editor')) {
        memoEditor = new Quill('#memo-editor', {
            theme: 'snow',
            placeholder: 'AIへの相談ごとやメモなど（太字やリストが使えます）',
            modules: {
                toolbar: [
                    ['bold', 'italic', 'underline'],
                    [{ 'list': 'ordered'}, { 'list': 'bullet' }],
                    ['clean']
                ]
            }
        });
    }

    // --- Tab Switching Logic ---
    const tabs = document.querySelectorAll('.nav-links li');
    const contents = document.querySelectorAll('.tab-content');

    tabs.forEach(tab => {
        tab.addEventListener('click', () => {
            tabs.forEach(t => t.classList.remove('active'));
            contents.forEach(c => c.classList.remove('active'));
            
            tab.classList.add('active');
            document.getElementById(tab.dataset.tab).classList.add('active');
            if (tab.dataset.tab === 'tab-daily' || tab.dataset.tab === 'tab-plan') {
                loadStudyStats(); // refresh stats
            }
        });
    });

    // --- Target & Aggregated Time Logic ---
    const dashboardTarget = document.getElementById('dashboard-target');
    const pomodoroSubject = document.getElementById('pomodoro-subject');
    const aggregatedTimeDisplay = document.getElementById('target-aggregated-time');

    async function fetchAggregatedTime(targetValue) {
        if (!targetValue) {
            aggregatedTimeDisplay.textContent = '--';
            return;
        }
        try {
            const res = await fetch('/api/study_coaching_hub', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({ phase: 'get_total_study_time', target: targetValue })
            });
            const data = await res.json();
            if (data.status === 'success') {
                aggregatedTimeDisplay.textContent = data.total_minutes;
            }
        } catch (e) {
            console.log("Failed to fetch aggregated time", e);
        }
    }

    function syncTargets(e) {
        const val = e.target.value;
        if (e.target.id === 'dashboard-target') {
            pomodoroSubject.value = val;
        } else if (e.target.id === 'pomodoro-subject') {
            dashboardTarget.value = val;
        }
        fetchAggregatedTime(val);
    }

    dashboardTarget.addEventListener('change', syncTargets);
    pomodoroSubject.addEventListener('change', syncTargets);

    // --- Pomodoro Timer ---
    let timerInterval;
    const POMODORO_DURATION = 25 * 60; // 25 minutes
    let timeLeft = POMODORO_DURATION;
    let totalStudyTimeMinutes = 0; // accumulated today
    const timerDisplay = document.getElementById('timer');
    const startBtn = document.getElementById('start-timer');
    const pauseBtn = document.getElementById('pause-timer');
    const finishBtn = document.getElementById('finish-timer');
    const resetBtn = document.getElementById('reset-timer');
    const totalTimeDisplay = document.getElementById('total-study-time');
    
    function updateTimerDisplay() {
        const m = Math.floor(timeLeft / 60).toString().padStart(2, '0');
        const s = (timeLeft % 60).toString().padStart(2, '0');
        timerDisplay.textContent = `${m}:${s}`;
        
        // Update the displayed total time dynamically
        const elapsedSessionMinutes = Math.floor((POMODORO_DURATION - timeLeft) / 60);
        totalTimeDisplay.textContent = totalStudyTimeMinutes + elapsedSessionMinutes;
    }

    async function addElapsedTimeToTotal() {
        const elapsedSeconds = POMODORO_DURATION - timeLeft;
        const elapsedMinutes = Math.floor(elapsedSeconds / 60);
        if (elapsedMinutes > 0) {
            totalStudyTimeMinutes += elapsedMinutes;
            totalTimeDisplay.textContent = totalStudyTimeMinutes;
            
            // Save to Pomodoro History
            const subject = document.getElementById('pomodoro-subject').value;
            try {
                await fetch('/api/study_coaching_hub', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({
                        phase: 'save_pomodoro',
                        subject: subject,
                        duration: elapsedMinutes
                    })
                });
            } catch (e) {
                console.log('Failed to save pomodoro', e);
            }
        }
    }

    startBtn.addEventListener('click', () => {
        startBtn.style.display = 'none';
        pauseBtn.style.display = 'inline-block';
        timerInterval = setInterval(() => {
            if (timeLeft > 0) {
                timeLeft--;
                updateTimerDisplay();
            } else {
                clearInterval(timerInterval);
                pauseBtn.style.display = 'none';
                startBtn.style.display = 'inline-block';
                // 25分経過
                addElapsedTimeToTotal();
                timeLeft = POMODORO_DURATION;
                updateTimerDisplay();
                alert('ポモドーロ完了！学習時間が記録されました。');
            }
        }, 1000);
    });

    pauseBtn.addEventListener('click', () => {
        clearInterval(timerInterval);
        pauseBtn.style.display = 'none';
        startBtn.style.display = 'inline-block';
    });

    finishBtn.addEventListener('click', () => {
        clearInterval(timerInterval);
        addElapsedTimeToTotal();
        timeLeft = POMODORO_DURATION;
        updateTimerDisplay();
        pauseBtn.style.display = 'none';
        startBtn.style.display = 'inline-block';
        alert('学習を終了しました。経過時間を記録に追加しました。');
    });

    resetBtn.addEventListener('click', () => {
        clearInterval(timerInterval);
        timeLeft = POMODORO_DURATION;
        updateTimerDisplay();
        pauseBtn.style.display = 'none';
        startBtn.style.display = 'inline-block';
    });

    // --- Graph Toggle & Stats ---
    const toggleGraphBtn = document.getElementById('toggle-graph-btn');
    if (toggleGraphBtn) {
        toggleGraphBtn.addEventListener('click', () => {
            const area = document.getElementById('graph-area');
            const icon = document.getElementById('graph-toggle-icon');
            if (area.style.display === 'none') {
                area.style.display = 'block';
                icon.textContent = '▼';
            } else {
                area.style.display = 'none';
                icon.textContent = '▶';
            }
        });
    }

    async function loadStudyStats() {
        try {
            const res = await fetch('/api/study_coaching_hub', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({ phase: 'get_study_stats' })
            });
            const data = await res.json();
            if (data.status === 'success') {
                const stats = data.stats;
                currentHeatmapData = stats.heatmap || {};
                updateChart('week'); // Init chart with week data
                document.querySelector('.streak-count').textContent = `${stats.streak} Days`;
                
                totalStudyTimeMinutes = stats.today_minutes;
                totalTimeDisplay.textContent = totalStudyTimeMinutes;

                const hmContainer = document.getElementById('heatmap-container');
                const hmMonths = document.getElementById('heatmap-months');
                if (hmContainer && hmMonths) {
                    hmContainer.innerHTML = '';
                    hmMonths.innerHTML = '';
                    
                    const today = new Date();
                    const currentDayOfWeek = today.getDay(); // 0=Sun
                    const WEEKS_TO_SHOW = 26;
                    const daysToSubtract = ((WEEKS_TO_SHOW - 1) * 7) + currentDayOfWeek;
                    
                    const startDate = new Date(today);
                    startDate.setDate(startDate.getDate() - daysToSubtract);
                    
                    let currentMonth = -1;
                    
                    for (let i = 0; i <= daysToSubtract; i++) {
                        const d = new Date(startDate);
                        d.setDate(d.getDate() + i);
                        const dateStr = d.toISOString().split('T')[0];
                        
                        // Check if it's the start of a week to potentially add a month label
                        if (d.getDay() === 0) {
                            if (d.getMonth() !== currentMonth) {
                                currentMonth = d.getMonth();
                                // Position month label based on the week index
                                const weekIndex = Math.floor(i / 7);
                                const leftPos = weekIndex * (12 + 4); // 12px box + 4px gap
                                const monthLabel = document.createElement('span');
                                monthLabel.style.position = 'absolute';
                                monthLabel.style.left = `${leftPos}px`;
                                monthLabel.textContent = `${currentMonth + 1}月`;
                                hmMonths.appendChild(monthLabel);
                            }
                        }
                        
                        const mins = stats.heatmap[dateStr] || 0;
                        let opacity = 0.1;
                        if (mins > 0) opacity = 0.3 + Math.min((mins / 60) * 0.7, 0.7);
                        const box = document.createElement('div');
                        box.style.width = '12px';
                        box.style.height = '12px';
                        box.style.borderRadius = '3px';
                        if (d > today) {
                            box.style.backgroundColor = 'transparent'; // Future days in the last column
                        } else {
                            box.style.backgroundColor = `rgba(59, 130, 246, ${opacity})`;
                            box.title = `${dateStr}: ${mins}分`;
                        }
                        hmContainer.appendChild(box);
                    }
                }
            }
        } catch(e) { console.log(e); }
    }
    loadStudyStats();

    // --- Fetch Past Subjects for Autocomplete ---
    async function loadPastSubjects() {
        try {
            const res = await fetch('/api/study_coaching_hub', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({ phase: 'get_past_subjects' })
            });
            const data = await res.json();
            if (data.status === 'success' && data.subjects) {
                const datalist = document.getElementById('past-subjects');
                datalist.innerHTML = '';
                data.subjects.forEach(sub => {
                    const option = document.createElement('option');
                    option.value = sub;
                    datalist.appendChild(option);
                });
            }
        } catch (err) {
            console.log('Failed to load past subjects', err);
        }
    }
    
    // --- Fetch Past Contents for Autocomplete ---
    async function loadPastContents() {
        try {
            const res = await fetch('/api/study_coaching_hub', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({ phase: 'get_past_contents' })
            });
            const data = await res.json();
            if (data.status === 'success' && data.contents) {
                const datalist = document.getElementById('past-contents');
                if (datalist) {
                    datalist.innerHTML = '';
                    data.contents.forEach(val => {
                        const option = document.createElement('option');
                        option.value = val;
                        datalist.appendChild(option);
                    });
                }
            }
        } catch (err) {
            console.log('Failed to load past contents', err);
        }
    }
    
    // Call them on load
    loadPastSubjects();
    loadPastContents();

    // --- Web Speech API (Feynman Mode) ---
    const voiceBtn = document.getElementById('voice-input-btn');
    const memoInput = document.getElementById('memo');
    
    if ('webkitSpeechRecognition' in window) {
        const recognition = new webkitSpeechRecognition();
        recognition.lang = 'ja-JP';
        recognition.continuous = false;
        recognition.interimResults = false;

        voiceBtn.addEventListener('click', () => {
            voiceBtn.textContent = '🎤 録音中...';
            recognition.start();
        });

        recognition.onresult = (event) => {
            const transcript = event.results[0][0].transcript;
            if (memoEditor) {
                const range = memoEditor.getSelection(true);
                memoEditor.insertText(range.index, transcript + '\n');
            }
            voiceBtn.textContent = '🎤 ファインマン・モード（音声入力）';
        };

        recognition.onerror = () => {
            voiceBtn.textContent = '🎤 ファインマン・モード（音声入力）';
            alert('音声認識に失敗しました。');
        };
    } else {
        voiceBtn.style.display = 'none'; // Not supported
    }

    // --- Chart.js Initialization ---
    const ctx = document.getElementById('progressChart').getContext('2d');
    const gradient = ctx.createLinearGradient(0, 0, 0, 400);
    gradient.addColorStop(0, 'rgba(59, 130, 246, 0.5)');   
    gradient.addColorStop(1, 'rgba(59, 130, 246, 0.0)');

    let progressChart = new Chart(ctx, {
        type: 'line',
        data: {
            labels: [],
            datasets: [{
                label: '学習時間 (分)',
                data: [],
                borderColor: '#3b82f6',
                backgroundColor: gradient,
                borderWidth: 2,
                pointBackgroundColor: '#60a5fa',
                pointBorderColor: '#fff',
                pointHoverBackgroundColor: '#fff',
                pointHoverBorderColor: '#3b82f6',
                fill: true,
                tension: 0.4
            }]
        },
        options: {
            responsive: true,
            plugins: {
                legend: { labels: { color: '#f8fafc' } }
            },
            scales: {
                y: {
                    beginAtZero: true,
                    grid: { color: 'rgba(255, 255, 255, 0.1)' },
                    ticks: { color: '#94a3b8' }
                },
                x: {
                    grid: { display: false },
                    ticks: { color: '#94a3b8' }
                }
            }
        }
    });

    let currentHeatmapData = {};
    
    function updateChart(mode) {
        if (!progressChart) return;
        const labels = [];
        const data = [];
        const today = new Date();
        
        if (mode === 'week') {
            for (let i = 6; i >= 0; i--) {
                const d = new Date(today);
                d.setDate(d.getDate() - i);
                const ds = d.toISOString().split('T')[0];
                labels.push(`${d.getDate()}日`);
                data.push(currentHeatmapData[ds] || 0);
            }
        } else if (mode === 'month') {
            for (let i = 3; i >= 0; i--) {
                let weekTotal = 0;
                for (let j = 0; j < 7; j++) {
                    const d = new Date(today);
                    d.setDate(d.getDate() - (i * 7 + j));
                    const ds = d.toISOString().split('T')[0];
                    weekTotal += (currentHeatmapData[ds] || 0);
                }
                data.push(weekTotal);
            }
            labels.push("3週間前", "2週間前", "先週", "今週");
        } else if (mode === 'year') {
            for (let i = 11; i >= 0; i--) {
                const targetMonth = new Date(today.getFullYear(), today.getMonth() - i, 1);
                const mStr = `${targetMonth.getFullYear()}-${String(targetMonth.getMonth() + 1).padStart(2, '0')}`;
                labels.push(`${targetMonth.getMonth() + 1}月`);
                let monthTotal = 0;
                for (const dateStr in currentHeatmapData) {
                    if (dateStr.startsWith(mStr)) {
                        monthTotal += currentHeatmapData[dateStr];
                    }
                }
                data.push(monthTotal);
            }
        }
        
        progressChart.data.labels = labels;
        progressChart.data.datasets[0].data = data;
        progressChart.update();
        
        // Update button styles
        ['week', 'month', 'year'].forEach(m => {
            const btn = document.getElementById(`btn-chart-${m}`);
            if (btn) btn.style.background = m === mode ? 'var(--accent-blue)' : 'rgba(255, 255, 255, 0.1)';
        });
    }

    document.getElementById('btn-chart-week').addEventListener('click', () => updateChart('week'));
    document.getElementById('btn-chart-month').addEventListener('click', () => updateChart('month'));
    document.getElementById('btn-chart-year').addEventListener('click', () => updateChart('year'));

    // --- API Calls (Stubs/Placeholders to be wired to Django) ---
    
    // Plan Submission (Draft)
    let currentDraftMilestones = [];
    document.getElementById('plan-form').addEventListener('submit', async (e) => {
        e.preventDefault();
        const btn = document.getElementById('draft-plan-btn');
        btn.textContent = '草案を作成中...';
        btn.disabled = true;

        const qual = document.getElementById('qualification').value;
        const dur = document.getElementById('duration').value;
        const syllabus = document.getElementById('syllabus') ? document.getElementById('syllabus').value : '';
        const constraints = document.getElementById('constraints') ? document.getElementById('constraints').value : '';

        try {
            const res = await fetch('/api/study_coaching_hub', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({
                    phase: 'draft_roadmap', 
                    qualification: qual, 
                    duration_months: parseInt(dur), 
                    syllabus: syllabus,
                    constraints: constraints,
                    system_prompt: localStorage.getItem('system_prompt') || ''
                })
            });
            const data = await res.json();
            if (data.status === 'success') {
                currentDraftMilestones = data.plan.milestones;
                document.getElementById('roadmap-container').style.display = 'block';
                const tl = document.getElementById('timeline');
                tl.innerHTML = '';
                currentDraftMilestones.forEach(m => {
                    tl.innerHTML += `<div style="margin-bottom:10px; padding:10px; background:rgba(255,255,255,0.05); border-radius:8px;">
                        <strong>第${m.week}週: ${m.topic}</strong> (目標: ${m.target_progress_percent}% | 平日: ${m.weekday_minutes || 60}分 / 休日: ${m.weekend_minutes || 120}分)<br>
                        <small style="color:#94a3b8;">${m.description}</small>
                    </div>`;
                });
                document.getElementById('sync-plan-btn').style.display = 'block';
                btn.textContent = '条件を変えて再提案 (AI)';
            }
        } catch (err) {
            alert('エラーが発生しました。');
            btn.textContent = 'ロードマップ草案を作成 (AI)';
        } finally {
            btn.disabled = false;
        }
    });

    // Plan Sync (Finalize)
    const syncPlanBtn = document.getElementById('sync-plan-btn');
    if (syncPlanBtn) {
        syncPlanBtn.addEventListener('click', async () => {
            const qual = document.getElementById('qualification').value;
            if (!qual || currentDraftMilestones.length === 0) return;
            
            syncPlanBtn.textContent = 'カレンダー連携中...';
            syncPlanBtn.disabled = true;
            try {
                const res = await fetch('/api/study_coaching_hub', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({
                        phase: 'sync_roadmap', 
                        qualification: qual, 
                        milestones: currentDraftMilestones
                    })
                });
                const data = await res.json();
                if (data.status === 'success') {
                    alert('カレンダーとシートに予定を登録しました！');
                    syncPlanBtn.style.display = 'none';
                }
            } catch (err) {
                alert('エラーが発生しました。');
            } finally {
                syncPlanBtn.textContent = 'この計画で確定しカレンダーに登録する';
                syncPlanBtn.disabled = false;
            }
        });
    }

    // Consultation Handling
    const consultForm = document.getElementById('consultation-form');
    if (consultForm) {
        consultForm.addEventListener('submit', async (e) => {
            e.preventDefault();
            faustAudio.volume = 0;
            faustAudio.src = 'data:audio/wav;base64,UklGRigAAABXQVZFZm10IBIAAAABAAEARKwAAIhYAQACABAAAABkYXRhAgAAAAEA';
            faustAudio.play().catch(e => {});

            const btn = document.getElementById('consult-plan-btn');
            btn.textContent = 'AIコーチに相談中...';
            btn.disabled = true;

            const qual = document.getElementById('qualification').value;
            const query = document.getElementById('consultation-query').value;
            
            if (!qual) {
                alert("目標資格を入力して「既存の計画を読み込む」か新規作成してから相談してください。");
                btn.textContent = 'AIコーチに相談する';
                btn.disabled = false;
                return;
            }

            try {
                const res = await fetch('/api/study_coaching_hub', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({
                        phase: 'consult_plan',
                        qualification: qual,
                        query: query,
                        speaker_id: localStorage.getItem('speaker_id') || 47,
                        system_prompt: localStorage.getItem('system_prompt') || ''
                    })
                });
                const data = await res.json();
                if (data.status === 'success') {
                    const resultDiv = document.getElementById('consultation-result');
                    resultDiv.style.display = 'block';
                    document.getElementById('consultation-advice').innerHTML = data.advice.replace(/\\n/g, '<br>');
                    
                    faustAudio.volume = parseFloat(localStorage.getItem('faust_volume') || 0.5);
                    faustAudio.src = '/static/current_coaching.wav?t=' + new Date().getTime();
                    faustAudio.play().catch(e => console.log('Audio playback failed', e));
                }
            } catch (err) {
                alert('エラーが発生しました。');
            } finally {
                btn.textContent = 'AIコーチに相談する';
                btn.disabled = false;
            }
        });
    }

    const playConsultBtn = document.getElementById('play-consultation-audio');
    if (playConsultBtn) {
        playConsultBtn.addEventListener('click', () => {
            faustAudio.volume = parseFloat(localStorage.getItem('faust_volume') || 0.5);
            faustAudio.src = '/static/current_coaching.wav?t=' + new Date().getTime();
            faustAudio.play().catch(e => alert('音声の再生に失敗しました。VOICEVOXが起動しているか確認してください。'));
        });
    }

    const fetchPlanBtn = document.getElementById('fetch-plan-btn');
    if (fetchPlanBtn) {
        fetchPlanBtn.addEventListener('click', async () => {
            const qual = document.getElementById('qualification').value;
            if (!qual) return alert('資格名を入力してください');
            
            fetchPlanBtn.textContent = '読込中...';
            try {
                const res = await fetch('/api/study_coaching_hub', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({phase: 'get_roadmap', target: qual})
                });
                const data = await res.json();
                if (data.status === 'success' && data.milestones.length > 0) {
                    document.getElementById('roadmap-container').style.display = 'block';
                    const tl = document.getElementById('timeline');
                    tl.innerHTML = '';
                    data.milestones.forEach(m => {
                        tl.innerHTML += `<div style="margin-bottom:10px; padding:10px; background:rgba(255,255,255,0.05); border-radius:8px;">
                            <strong>第${m.week}週: ${m.topic}</strong> (目標: ${m.target_progress_percent}% | 推奨学習時間: ${m.recommended_hours || "設定なし"})<br>
                        </div>`;
                    });
                } else {
                    alert('この資格の計画は見つかりませんでした。');
                }
            } catch (e) {
                alert('エラーが発生しました。');
            } finally {
                fetchPlanBtn.textContent = '既存の計画を読み込む';
            }
        });
    }

    // Daily Record Submission
    document.getElementById('daily-form').addEventListener('submit', async (e) => {
        e.preventDefault();
        
        // Unlock Audio Context immediately on user interaction
        faustAudio.volume = 0;
        faustAudio.src = 'data:audio/wav;base64,UklGRigAAABXQVZFZm10IBIAAAABAAEARKwAAIhYAQACABAAAABkYXRhAgAAAAEA';
        faustAudio.play().catch(e => {});

        const btn = document.getElementById('submit-daily-btn');
        btn.textContent = 'AIコーチが分析中...';
        btn.disabled = true;

        const target = document.getElementById('pomodoro-subject').value;
        const content = document.getElementById('content').value;
        const prog = document.getElementById('progress').value;
        const memoHtml = memoEditor ? memoEditor.root.innerHTML : '';
        const memoText = memoEditor ? memoEditor.getText() : '';
        // Mock date
        const date = new Date().toISOString().split('T')[0];

        try {
            const res = await fetch('/api/study_coaching_hub', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({
                    phase: 'daily_report', 
                    date: date, 
                    target: target, 
                    content: content,
                    memo: memoText,
                    study_time: totalStudyTimeMinutes,
                    progress_volume: prog,
                    speaker_id: localStorage.getItem('speaker_id') || 47,
                    system_prompt: localStorage.getItem('system_prompt') || ''
                })
            });
            const data = await res.json();
            if (data.status === 'success') {
                const resDiv = document.getElementById('coaching-result');
                resDiv.style.display = 'block';
                document.getElementById('daily-rating').textContent = `Rating: ${data.evaluation.daily_rating}`;
                document.getElementById('coaching-comment').textContent = data.evaluation.coaching_comment;
                
                // Reset accumulated time after submission
                totalStudyTimeMinutes = 0;
                totalTimeDisplay.textContent = '0';
                
                // Re-fetch aggregated time for the target
                fetchAggregatedTime(target);

                // Play the generated audio automatically
                faustAudio.volume = parseFloat(localStorage.getItem('faust_volume') || 0.5);
                faustAudio.src = '/static/current_coaching.wav?t=' + new Date().getTime();
                faustAudio.play().catch(e => console.log('Audio playback failed', e));
            }
        } catch (err) {
            alert('エラーが発生しました。');
        } finally {
            btn.textContent = '記録を送信してコーチングを受ける';
            btn.disabled = false;
        }
    });

    // Audio Playback for Coaching (Manual Button)
    document.getElementById('play-coaching-audio').addEventListener('click', () => {
        faustAudio.volume = parseFloat(localStorage.getItem('faust_volume') || 0.5);
        faustAudio.src = '/static/current_coaching.wav?t=' + new Date().getTime();
        faustAudio.play().catch(e => alert('音声の再生に失敗しました。VOICEVOXが起動しているか確認してください。'));
    });

    // Quiz Generation
    let currentQuizGlossary = "";
    document.getElementById('generate-quiz-btn').addEventListener('click', async (e) => {
        const btn = e.target;
        const targetVal = document.getElementById('quiz-target').value;
        if (!targetVal) {
            alert("目標資格を入力してください");
            return;
        }
        btn.textContent = '生成中... (数秒かかります)';
        btn.disabled = true;
        const qFormat = document.getElementById('quiz-format') ? document.getElementById('quiz-format').value : "記述式";

        try {
            const res = await fetch('/api/study_coaching_hub', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({ 
                    phase: 'generate_quiz', 
                    target: targetVal, 
                    quiz_format: qFormat, 
                    weakness_mode: false,
                    system_prompt: localStorage.getItem('system_prompt') || ''
                })
            });
            const data = await res.json();
            if (data.status === 'success') {
                const quizData = data.quiz_data;
                document.getElementById('quiz-container').style.display = 'block';
                
                // Render Glossary
                let glossaryHtml = '<ul>';
                currentQuizGlossary = "";
                quizData.glossary.forEach(g => {
                    glossaryHtml += `<li><strong>${g.term}:</strong> ${g.definition}</li>`;
                    currentQuizGlossary += `${g.term}: ${g.definition}\n`;
                });
                glossaryHtml += '</ul>';
                document.getElementById('glossary-content').innerHTML = glossaryHtml;
                
                // Render Question
                document.getElementById('quiz-question').textContent = quizData.question;
                
                // Hide result card if previously shown
                document.getElementById('quiz-result-card').style.display = 'none';
                document.getElementById('quiz-answer').value = '';
            }
        } catch (err) {
            alert('エラーが発生しました。');
        } finally {
            btn.textContent = '今日の学習内容とテストを生成する';
            btn.disabled = false;
        }
    });

    // Weakness Quiz Generation
    const weakQuizBtn = document.getElementById('weakness-quiz-btn');
    if (weakQuizBtn) {
        weakQuizBtn.addEventListener('click', async (e) => {
            const targetVal = document.getElementById('quiz-target').value;
            if (!targetVal) return alert("目標資格を入力してください");
            
            e.target.textContent = '弱点分析中...';
            e.target.disabled = true;
            const qFormat = document.getElementById('quiz-format') ? document.getElementById('quiz-format').value : "記述式";

            try {
                const res = await fetch('/api/study_coaching_hub', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({ 
                        phase: 'generate_quiz', 
                        target: targetVal, 
                        quiz_format: qFormat, 
                        weakness_mode: true,
                        system_prompt: localStorage.getItem('system_prompt') || ''
                    })
                });
                const data = await res.json();
                if (data.status === 'success') {
                    const quizData = data.quiz_data;
                    document.getElementById('quiz-container').style.display = 'block';
                    let glossaryHtml = '<ul>';
                    currentQuizGlossary = "";
                    quizData.glossary.forEach(g => {
                        glossaryHtml += `<li><strong>${g.term}:</strong> ${g.definition}</li>`;
                        currentQuizGlossary += `${g.term}: ${g.definition}\n`;
                    });
                    glossaryHtml += '</ul>';
                    document.getElementById('glossary-content').innerHTML = glossaryHtml;
                    document.getElementById('quiz-question').innerHTML = `<span style="color:var(--warning);">[弱点克服]</span> ${quizData.question}`;
                    document.getElementById('quiz-result-card').style.display = 'none';
                    document.getElementById('quiz-answer').value = '';
                } else {
                    alert(data.message || 'エラーが発生しました。');
                }
            } catch(err) { alert('エラー'); }
            e.target.textContent = '🔥 弱点克服モードで再出題';
            e.target.disabled = false;
        });
    }

    // Quiz Evaluation
    const evaluateQuizBtn = document.getElementById('quiz-answer-form');
    evaluateQuizBtn.addEventListener('submit', async (e) => {
        e.preventDefault();
        // Unlock Audio Context
        faustAudio.volume = 0;
        faustAudio.src = 'data:audio/wav;base64,UklGRigAAABXQVZFZm10IBIAAAABAAEARKwAAIhYAQACABAAAABkYXRhAgAAAAEA';
        faustAudio.play().catch(e => {});

        const btn = document.getElementById('submit-quiz-btn');
        btn.textContent = '採点中... (数秒かかります)';
        btn.disabled = true;

        const answer = document.getElementById('quiz-answer').value;
        const target = document.getElementById('quiz-target').value;
        const qFormat = document.getElementById('quiz-format') ? document.getElementById('quiz-format').value : "記述式";
        const date = new Date().toISOString().split('T')[0];

        try {
            const res = await fetch('/api/study_coaching_hub', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({
                    phase: 'evaluate_quiz',
                    date: date,
                    target: target,
                    quiz_format: qFormat,
                    glossary: currentQuizGlossary,
                    user_answer: answer,
                    speaker_id: localStorage.getItem('speaker_id') || 47,
                    system_prompt: localStorage.getItem('system_prompt') || ''
                })
            });
            const data = await res.json();
            if (data.status === 'success') {
                document.getElementById('quiz-result-card').style.display = 'block';
                const evalData = data.evaluation;
                document.getElementById('quiz-evaluation').innerHTML = `
                    <p><strong>判定:</strong> <span style="color: ${evalData.is_correct.includes('正解') ? 'var(--success)' : 'var(--danger)'}">${evalData.is_correct}</span></p>
                    <p><strong>模範解答・解説:</strong> ${evalData.correct_answer}</p>
                    <p><strong>フィードバック:</strong> ${evalData.feedback}</p>
                `;
                
                // Play the generated audio automatically
                faustAudio.volume = parseFloat(localStorage.getItem('faust_volume') || 0.5);
                faustAudio.src = '/static/current_coaching.wav?t=' + new Date().getTime();
                faustAudio.play().catch(e => console.log('Audio playback failed', e));
            }
        } catch (err) {
            alert('採点エラーが発生しました。');
        } finally {
            btn.textContent = '回答を送信して採点する';
            btn.disabled = false;
        }
    });

    // Audio Playback for Quiz (Manual Button)
    document.getElementById('play-quiz-audio').addEventListener('click', () => {
        faustAudio.volume = parseFloat(localStorage.getItem('faust_volume') || 0.5);
        faustAudio.src = '/static/current_coaching.wav?t=' + new Date().getTime();
        faustAudio.play().catch(e => alert('音声の再生に失敗しました。VOICEVOXが起動しているか確認してください。'));
    });
});
