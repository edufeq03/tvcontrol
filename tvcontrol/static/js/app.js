const urlParams = new URLSearchParams(window.location.search);
        let token = urlParams.get('token') || localStorage.getItem('tvcontrol_token') || localStorage.getItem('termcontrol_token') || '';
        if (urlParams.get('token')) {
            localStorage.setItem('tvcontrol_token', urlParams.get('token'));
            localStorage.setItem('termcontrol_token', urlParams.get('token'));
        }

        function apiFetch(url, options = {}) {
            if (!options.headers) options.headers = {};
            options.credentials = 'same-origin';
            if (token) {
                options.headers['X-Auth-Token'] = token;
            }
            return fetch(url, options).then(res => {
                if (res.status === 401) {
                    window.location.href = '/login';
                }
                return res;
            });
        }

        let pendingCmd = null;
        let pendingLabel = null;
        let toastTimeout;

        function showToast(msg) {
            const toast = document.getElementById('toast');
            toast.textContent = msg;
            toast.classList.add('show');
            clearTimeout(toastTimeout);
            toastTimeout = setTimeout(() => {
                toast.classList.remove('show');
            }, 1800);
        }

        // Funções do Modal QR Code
        function abrirModalQR() {
            document.getElementById('qrModal').classList.add('active');
        }

        function fecharModalQR() {
            document.getElementById('qrModal').classList.remove('active');
        }

        function copiarLinkConexao() {
            const input = document.getElementById('qrUrlInput');
            input.select();
            input.setSelectionRange(0, 99999);
            navigator.clipboard.writeText(input.value).then(() => {
                showToast('Link copiado para a área de transferência!');
                const icon = document.getElementById('copyIcon');
                icon.textContent = '✓';
                setTimeout(() => { icon.textContent = '📋'; }, 2000);
            }).catch(() => {
                showToast('Selecione e copie o endereço exibido.');
            });
        }

        // Sistema de Abas
        function switchTab(tabId) {
            if (navigator.vibrate) navigator.vibrate(20);
            document.querySelectorAll('.bottom-tab-btn, .tab-btn').forEach(btn => btn.classList.remove('active'));
            document.querySelectorAll('.tab-view').forEach(view => view.classList.remove('active'));

            const activeBtn = document.getElementById(`tab-${tabId}`);
            if (activeBtn) activeBtn.classList.add('active');
            const activeView = document.getElementById(`view-${tabId}`);
            if (activeView) activeView.classList.add('active');

            if (tabId === 'touchpad') {
                document.body.classList.add('touchpad-active');
            } else {
                document.body.classList.remove('touchpad-active');
            }

            if (tabId === 'timer') {
                checkTimerStatus();
            } else if (tabId === 'controls') {
                carregarVolume();
            }
        }

        // Toggle Painel de Teclado
        function toggleKeyboardPanel() {
            const kb = document.getElementById('keyboardBox');
            const icon = document.getElementById('keyboardToggleIcon');
            if (!kb) return;
            const isHidden = (kb.style.display === 'none' || !kb.style.display);
            if (isHidden) {
                kb.style.display = 'flex';
                if (icon) icon.textContent = '▲';
                const input = document.getElementById('keyboardInput');
                if (input) setTimeout(() => input.focus(), 100);
            } else {
                kb.style.display = 'none';
                if (icon) icon.textContent = '▼';
            }
        }

        // Volume em tempo real
        let volumeDebounceTimeout;
        function carregarVolume() {
            fetch('/volume?token=' + encodeURIComponent(token))
                .then(r => r.json())
                .then(data => {
                    if (data.status === 'ok') {
                        atualizarUIVolume(data.volume, data.muted);
                    }
                }).catch(() => {});
        }

        function atualizarUIVolume(vol, muted) {
            const slider = document.getElementById('volSlider');
            const percent = document.getElementById('volPercent');
            const icon = document.getElementById('volIcon');
            const btn = document.getElementById('volMuteBtn');
            if (!slider || !percent) return;

            slider.value = vol;
            percent.textContent = vol + '%';
            if (muted) {
                icon.textContent = '🔇';
                btn.classList.add('muted');
            } else {
                icon.textContent = vol > 50 ? '🔊' : (vol > 0 ? '🔉' : '🔈');
                btn.classList.remove('muted');
            }
        }

        function onVolumeSliderChange(val) {
            document.getElementById('volPercent').textContent = val + '%';
            clearTimeout(volumeDebounceTimeout);
            volumeDebounceTimeout = setTimeout(() => {
                fetch('/volume?token=' + encodeURIComponent(token), {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ volume: parseInt(val) })
                });
            }, 80);
        }

        function alternarMudo() {
            fetch('/volume?token=' + encodeURIComponent(token), {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ mute: 'toggle' })
            }).then(() => carregarVolume());
        }

        // Teclado / Digitação no PC
        function enviarTextoDigitado(e) {
            e.preventDefault();
            const input = document.getElementById('keyboardInput');
            const texto = input.value;
            if (!texto) return;
            fetch('/type?token=' + encodeURIComponent(token), {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ text: texto, enter: true })
            }).then(r => r.json()).then(() => {
                showToast(`Digitado: "${texto}"`);
                input.value = '';
                input.blur();
            }).catch(() => {
                showToast('Erro ao enviar texto para o PC');
            });
        }

        function enviarTecla(tecla) {
            if (navigator.vibrate) navigator.vibrate(15);
            fetch('/key?token=' + encodeURIComponent(token), {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ key: tecla })
            }).then(() => {
                showToast(`Tecla: ${tecla}`);
            }).catch(() => {});
        }

        // Inicializar volume ao carregar
        window.addEventListener('DOMContentLoaded', () => {
            carregarVolume();
        });

        // Executar Comandos de Mídia
        async function executar(btnId, label) {
            if (navigator.vibrate) navigator.vibrate(30);
            try {
                const res = await fetch(`/exec/${btnId}?token=${encodeURIComponent(token)}`, {
                    method: 'POST',
                    headers: { 'X-Auth-Token': token }
                });
                if (res.ok) {
                    showToast(`✓ ${label}`);
                    if (btnId.includes('vol') || btnId === 'mudo') {
                        setTimeout(carregarVolume, 150);
                    }
                } else if (res.status === 401) {
                    showToast('⚠️ Erro: Token inválido!');
                } else {
                    showToast(`⚠️ Falha ao executar ${label}`);
                }
            } catch (e) {
                showToast('❌ Falha na conexão');
            }
        }

        // Confirmação
        function abrirConfirmacao(btnId, label, sub) {
            if (navigator.vibrate) navigator.vibrate(45);
            pendingCmd = btnId;
            pendingLabel = label;
            document.getElementById('modalTitle').textContent = `Executar ${label}?`;
            document.getElementById('modalDesc').textContent = sub ? `${sub}. Deseja continuar?` : 'Deseja realmente executar esta ação?';
            document.getElementById('confirmModal').classList.add('active');
        }

        function fecharConfirmacao() {
            document.getElementById('confirmModal').classList.remove('active');
            pendingCmd = null;
            pendingLabel = null;
        }

        function confirmarExecucao() {
            if (pendingCmd) {
                const id = pendingCmd;
                const label = pendingLabel;
                fecharConfirmacao();
                executar(id, label);
            }
        }

        // ==========================================
        // 🖱️ TOUCHPAD / MOUSE VIRTUAL
        // ==========================================
        const touchpad = document.getElementById('touchpad-surface');
        let lastX = 0, lastY = 0;
        let startX = 0, startY = 0;
        let startTime = 0;
        let isTouchMoving = false;
        let isTwoFinger = false;
        let accumDX = 0, accumDY = 0;
        let isSendingMove = false;
        let scrollAccum = 0;

        function flushMouseMove() {
            if (Math.abs(accumDX) < 1 && Math.abs(accumDY) < 1) {
                isSendingMove = false;
                return;
            }
            const sendX = Math.trunc(accumDX);
            const sendY = Math.trunc(accumDY);
            accumDX -= sendX;
            accumDY -= sendY;
            fetch(`/mouse/move?dx=${sendX}&dy=${sendY}&token=${encodeURIComponent(token)}`, { method: 'POST' })
                .finally(() => {
                    if (Math.abs(accumDX) >= 1 || Math.abs(accumDY) >= 1) {
                        requestAnimationFrame(flushMouseMove);
                    } else {
                        isSendingMove = false;
                    }
                });
        }

        touchpad.addEventListener('touchstart', (e) => {
            startTime = Date.now();
            isTwoFinger = e.touches.length >= 2;
            const t = e.touches[0];
            startX = t.clientX;
            startY = t.clientY;
            lastX = t.clientX;
            lastY = t.clientY;
            isTouchMoving = false;
            scrollAccum = 0;
        }, { passive: false });

        touchpad.addEventListener('touchmove', (e) => {
            e.preventDefault();
            const rect = touchpad.getBoundingClientRect();
            const t = e.touches[0];
            const inScrollStrip = (t.clientX >= rect.right - 54);
            const isTwo = (e.touches.length >= 2) || isTwoFinger;

            const dx = (t.clientX - lastX) * 1.5;
            const dy = (t.clientY - lastY) * 1.5;
            lastX = t.clientX;
            lastY = t.clientY;

            if (Math.hypot(t.clientX - startX, t.clientY - startY) > 5) {
                isTouchMoving = true;
            }

            // Modo Rolagem (Barra lateral ou 2 dedos)
            if (inScrollStrip || isTwo) {
                scrollAccum += dy;
                if (Math.abs(scrollAccum) >= 8) {
                    const dir = scrollAccum < 0 ? 1 : -1;
                    scrollAccum = 0;
                    fetch(`/mouse/scroll?delta=${dir}&token=${encodeURIComponent(token)}`, { method: 'POST' });
                }
            } else {
                // Modo Movimento do Mouse
                accumDX += dx;
                accumDY += dy;
                if (!isSendingMove && (Math.abs(accumDX) >= 1 || Math.abs(accumDY) >= 1)) {
                    isSendingMove = true;
                    requestAnimationFrame(flushMouseMove);
                }
            }
        }, { passive: false });

        touchpad.addEventListener('touchend', (e) => {
            const elapsed = Date.now() - startTime;
            if (!isTouchMoving && elapsed < 260) {
                if (navigator.vibrate) navigator.vibrate(25);
                if (isTwoFinger || (e.changedTouches && e.changedTouches.length >= 2)) {
                    sendMouseClick(3); // botão direito
                } else {
                    sendMouseClick(1); // clique esquerdo
                }
            }
            isTouchMoving = false;
            isTwoFinger = false;
        });

        touchpad.addEventListener('touchcancel', () => {
            isTouchMoving = false;
            isTwoFinger = false;
            accumDX = 0;
            accumDY = 0;
            scrollAccum = 0;
        });

        async function sendMouseClick(btn) {
            if (navigator.vibrate) navigator.vibrate(30);
            showToast(btn === 1 ? '🖱️ Clique Esquerdo' : '🖱️ Clique Direito');
            fetch(`/mouse/click?button=${btn}&token=${encodeURIComponent(token)}`, { method: 'POST' });
        }

        // ==========================================
        // ⏱️ MODO SLEEP / TEMPORIZADOR
        // ==========================================
        let timerCountdownInterval = null;
        let remainingSeconds = 0;

        async function checkTimerStatus() {
            try {
                const res = await fetch(`/timer/status?token=${encodeURIComponent(token)}`);
                const data = await res.json();
                if (data.active && data.remaining_seconds > 0) {
                    remainingSeconds = data.remaining_seconds;
                    updateTimerDisplay(true);
                } else {
                    updateTimerDisplay(false);
                }
            } catch (e) {}
        }

        async function setTimer(minutes) {
            if (navigator.vibrate) navigator.vibrate(35);
            try {
                const res = await fetch(`/timer/set?minutes=${minutes}&token=${encodeURIComponent(token)}`, { method: 'POST' });
                const data = await res.json();
                remainingSeconds = data.remaining_seconds;
                updateTimerDisplay(true);
                showToast(`⏳ Timer de ${minutes} min ativado!`);
            } catch (e) {
                showToast('❌ Erro ao definir timer');
            }
        }

        async function cancelTimer() {
            if (navigator.vibrate) navigator.vibrate(30);
            try {
                await fetch(`/timer/cancel?token=${encodeURIComponent(token)}`, { method: 'POST' });
                clearInterval(timerCountdownInterval);
                updateTimerDisplay(false);
                showToast('✓ Temporizador cancelado');
            } catch (e) {
                showToast('❌ Erro ao cancelar timer');
            }
        }

        function updateTimerDisplay(isActive) {
            clearInterval(timerCountdownInterval);
            const statusText = document.getElementById('timerStatusText');
            const countdown = document.getElementById('timerCountdown');
            const btnCancel = document.getElementById('btnCancelTimer');

            if (!isActive) {
                statusText.textContent = 'Nenhum temporizador ativo';
                countdown.textContent = '--:--';
                countdown.classList.remove('active-countdown');
                btnCancel.style.display = 'none';
                return;
            }

            statusText.textContent = 'Desligamento automático ativo';
            countdown.classList.add('active-countdown');
            btnCancel.style.display = 'inline-block';

            function renderSeconds() {
                if (remainingSeconds <= 0) {
                    clearInterval(timerCountdownInterval);
                    countdown.textContent = '00:00';
                    statusText.textContent = 'Desligando agora...';
                    return;
                }
                const m = Math.floor(remainingSeconds / 60);
                const s = remainingSeconds % 60;
                countdown.textContent = `${String(m).padStart(2, '0')}:${String(s).padStart(2, '0')}`;
                remainingSeconds--;
            }

            renderSeconds();
            timerCountdownInterval = setInterval(renderSeconds, 1000);
        }

        // Checagem inicial de timer ao carregar
        checkTimerStatus();

        // Delegação de eventos para botões de controle (data-btn-id)
        document.addEventListener('click', (e) => {
            const btn = e.target.closest('[data-btn-id]');
            if (!btn) return;
            const btnId = btn.dataset.btnId;
            const label = btn.dataset.label || btnId;
            const sub = btn.dataset.sub || '';
            const needsConfirm = btn.dataset.confirm === 'true';
            if (needsConfirm) {
                abrirConfirmacao(btnId, label, sub);
            } else {
                executar(btnId, label);
            }
        });

        // ==========================================
        // 💓 MONITORAMENTO DE CONEXÃO EM TEMPO REAL
        // ==========================================
        let wasOffline = false;
        function checkConnection() {
            const dot = document.getElementById('connStatusDot');
            const txt = document.getElementById('connStatusText');
            if (!dot || !txt) return;

            fetch('/ping', { credentials: 'same-origin', cache: 'no-store' })
                .then(r => r.json())
                .then(data => {
                    if (data && data.status === 'ok') {
                        dot.style.background = '#22c55e';
                        dot.style.boxShadow = '0 0 8px rgba(34, 197, 94, 0.6)';
                        txt.textContent = 'Online';
                        if (wasOffline) {
                            showToast('🟢 Reconectado ao servidor!');
                            wasOffline = false;
                        }
                    } else {
                        throw new Error('Invalid response');
                    }
                })
                .catch(() => {
                    dot.style.background = '#ef4444';
                    dot.style.boxShadow = '0 0 8px rgba(239, 68, 68, 0.6)';
                    txt.textContent = 'Offline';
                    if (!wasOffline) {
                        showToast('⚠️ Conexão perdida. Tentando reconectar...');
                        wasOffline = true;
                    }
                });
        }
        setInterval(checkConnection, 4000);