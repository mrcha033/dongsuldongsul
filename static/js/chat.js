// 채팅 관련 전역 변수
let currentTableId = null;
let websocket = null;
let isConnected = false;

// 개인 메시지 관련 변수
let isPrivateMode = false;
let targetTableId = null;
let targetNickname = null;

// 주문 모달 관련 변수
let currentStep = 1;
let selectedTableId = null;
let orderItems = {};
let menuData = {};

// 페이지 로드 시 초기화 (테이블 ID가 있는 경우)
function initializeChat(tableId) {
    console.log('initializeChat called with tableId:', tableId);
    currentTableId = parseInt(tableId);
    console.log('currentTableId set to:', currentTableId);
    
    if (isNaN(currentTableId)) {
        console.error('Invalid table ID provided:', tableId);
        alert('유효하지 않은 테이블 ID입니다.');
        return;
    }
    
    connectWebSocket();
    loadRecentMessages();
    loadOnlineUsers();
    
    // 메시지 입력 시 엔터키 처리
    const messageInput = document.getElementById('message-input');
    if (messageInput) {
        messageInput.addEventListener('keypress', function(e) {
            if (e.key === 'Enter') {
                sendMessage();
            }
        });
    }
    
    // 닉네임 입력 시 엔터키 처리
    const nicknameInput = document.getElementById('nickname-input');
    if (nicknameInput) {
        nicknameInput.addEventListener('keypress', function(e) {
            if (e.key === 'Enter') {
                const msgInput = document.getElementById('message-input');
                if (msgInput) msgInput.focus();
            }
        });
    }
    
    // 5초마다 온라인 사용자 목록 업데이트
    setInterval(loadOnlineUsers, 5000);
}

// 테이블 입장 (테이블 ID가 없는 경우)
function joinChat() {
    const tableNumberInput = document.getElementById('table-number-input');
    if (!tableNumberInput) return;
    
    const tableNumber = tableNumberInput.value;
    if (tableNumber && tableNumber >= 1 && tableNumber <= 50) {
        window.location.href = `/chat/${tableNumber}`;
    } else {
        alert('1-50 사이의 테이블 번호를 입력해주세요.');
    }
}

// 테이블 번호 입력에서 엔터키 처리
function initializeTableInput() {
    const tableNumberInput = document.getElementById('table-number-input');
    if (tableNumberInput) {
        tableNumberInput.addEventListener('keypress', function(e) {
            if (e.key === 'Enter') {
                joinChat();
            }
        });
    }
}

// WebSocket 연결
function connectWebSocket() {
    if (!currentTableId) {
        console.warn('Cannot connect WebSocket: currentTableId is not set');
        return;
    }
    
    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    const wsUrl = `${protocol}//${window.location.host}/ws/${currentTableId}`;
    
    console.log('Attempting WebSocket connection to:', wsUrl);
    
    try {
        websocket = new WebSocket(wsUrl);
        
        websocket.onopen = function(event) {
            isConnected = true;
            updateConnectionStatus('connected');
            console.log('WebSocket 연결 성공:', wsUrl);
            
            // 연결 성공 시 폴링 중지
            if (window.messagePollingInterval) {
                clearInterval(window.messagePollingInterval);
                window.messagePollingInterval = null;
            }
        };
        
        websocket.onmessage = function(event) {
            try {
                const data = JSON.parse(event.data);
                console.log('WebSocket message received:', data);
                
                if (data.type === 'chat_message') {
                    addMessageToChat(data);
                } else if (data.type === 'gift_order') {
                    handleGiftOrderNotification(data);
                } else if (data.type === 'gift_announcement') {
                    handleGiftAnnouncement(data);
                }
            } catch (error) {
                console.error('Error parsing WebSocket message:', error, event.data);
            }
        };
        
        websocket.onclose = function(event) {
            isConnected = false;
            updateConnectionStatus('disconnected');
            console.log('WebSocket 연결 끊어짐. Code:', event.code, 'Reason:', event.reason);
            
            // WebSocket 실패 시 폴링으로 대체
            startMessagePolling();
            
            // 5초 후 재연결 시도 (최대 3번)
            if (!window.wsRetryCount) window.wsRetryCount = 0;
            if (window.wsRetryCount < 3) {
                window.wsRetryCount++;
                console.log(`WebSocket 재연결 시도 ${window.wsRetryCount}/3`);
                setTimeout(connectWebSocket, 5000);
            } else {
                console.log('WebSocket 재연결 포기. 폴링 모드로 전환.');
                updateConnectionStatus('polling');
            }
        };
        
        websocket.onerror = function(error) {
            console.error('WebSocket 오류:', error);
            console.error('WebSocket state:', websocket.readyState);
            updateConnectionStatus('error');
        };
        
    } catch (error) {
        console.error('WebSocket 생성 실패:', error);
        startMessagePolling();
    }
}

// 메시지 폴링 시작 (WebSocket 대안)
function startMessagePolling() {
    if (window.messagePollingInterval) {
        return; // 이미 폴링 중
    }
    
    console.log('Starting message polling as WebSocket fallback');
    
    let lastMessageId = 0;
    
    window.messagePollingInterval = setInterval(async () => {
        try {
            const url = `/chat/messages?limit=10${currentTableId ? `&table_id=${currentTableId}` : ''}${lastMessageId ? `&after_id=${lastMessageId}` : ''}`;
            const response = await fetch(url);
            
            if (response.ok) {
                const data = await response.json();
                if (data.messages && data.messages.length > 0) {
                    data.messages.forEach(message => {
                        if (message.id > lastMessageId) {
                            addMessageToChat(message);
                            lastMessageId = message.id;
                        }
                    });
                }
            }
        } catch (error) {
            console.error('Polling error:', error);
        }
    }, 3000); // 3초마다 새 메시지 확인
}

// 연결 상태 업데이트
function updateConnectionStatus(status) {
    const statusElement = document.getElementById('chat-status');
    if (!statusElement) return;
    
    switch(status) {
        case 'connected':
            statusElement.textContent = '✅ 연결됨';
            statusElement.style.backgroundColor = 'var(--success-color)';
            statusElement.style.display = 'none';
            break;
        case 'disconnected':
            statusElement.textContent = '❌ 연결 끊어짐 - 재연결 시도 중...';
            statusElement.style.backgroundColor = 'var(--danger-color)';
            statusElement.style.display = 'block';
            break;
        case 'error':
            statusElement.textContent = '⚠️ 연결 오류';
            statusElement.style.backgroundColor = 'var(--warning-color)';
            statusElement.style.display = 'block';
            break;
        case 'polling':
            statusElement.textContent = '❌ 연결 끊어짐 - 폴링 모드 중...';
            statusElement.style.backgroundColor = 'var(--warning-color)';
            statusElement.style.display = 'block';
            break;
    }
}

// 최근 메시지 로드
async function loadRecentMessages() {
    try {
        const url = `/chat/messages?limit=30${currentTableId ? `&table_id=${currentTableId}` : ''}`;
        const response = await fetch(url);
        console.log('Messages response status:', response.status);
        
        if (!response.ok) {
            throw new Error(`HTTP error! status: ${response.status}`);
        }
        
        const data = await response.json();
        console.log('Messages response data:', data);
        
        const chatMessages = document.getElementById('chat-messages');
        if (!chatMessages) return;
        
        chatMessages.innerHTML = '';
        
        // 응답 데이터 구조 검증
        if (!data || !data.messages || !Array.isArray(data.messages)) {
            console.error('Invalid messages response format:', data);
            chatMessages.innerHTML = '<div class="loading">메시지 데이터 형식이 올바르지 않습니다.</div>';
            return;
        }
        
        if (data.messages.length === 0) {
            chatMessages.innerHTML = '<div class="loading">아직 메시지가 없습니다. 첫 번째 메시지를 보내보세요! 🌟</div>';
        } else {
            data.messages.forEach(message => {
                addMessageToChat(message, false);
            });
            scrollToBottom();
        }
    } catch (error) {
        console.error('메시지 로드 오류:', error);
        const chatMessages = document.getElementById('chat-messages');
        if (chatMessages) {
            chatMessages.innerHTML = '<div class="loading">메시지를 불러올 수 없습니다.</div>';
        }
    }
}

// 온라인 사용자 로드
async function loadOnlineUsers() {
    try {
        console.log('Loading online users...');
        const response = await fetch('/chat/online-tables');
        console.log('Online users response status:', response.status);
        
        if (!response.ok) {
            const errorText = await response.text();
            console.error('Online users error response:', errorText);
            throw new Error(`HTTP error! status: ${response.status}, body: ${errorText}`);
        }
        
        const data = await response.json();
        console.log('Online users response data:', data);
        
        const onlineList = document.getElementById('online-users-list');
        const onlineCount = document.getElementById('online-count');
        
        // DOM 요소가 존재하지 않으면 리턴
        if (!onlineList || !onlineCount) {
            console.warn('Online users DOM elements not found');
            return;
        }
        
        // 응답 데이터 유효성 검사
        if (!data || !Array.isArray(data.online_tables)) {
            console.warn('Invalid response format:', data);
            onlineList.innerHTML = '<div class="online-user">접속자 정보를 불러올 수 없습니다</div>';
            onlineCount.textContent = '0명';
            return;
        }
        
        if (data.online_tables.length === 0) {
            onlineList.innerHTML = '<div class="online-user">아직 접속자가 없습니다</div>';
            onlineCount.textContent = '0명';
        } else {
            // 자신을 제외한 온라인 테이블만 표시
            const otherTables = data.online_tables.filter(table => table.table_id !== currentTableId);
            
            if (otherTables.length === 0) {
                onlineList.innerHTML = '<div class="online-user">다른 접속자가 없습니다</div>';
                onlineCount.textContent = '1명 (나만)';
            } else {
                onlineList.innerHTML = otherTables.map(table => 
                    `<div class="online-user clickable" data-table-id="${table.table_id}" data-nickname="${table.nickname}">
                        ${table.nickname || `테이블${table.table_id}`}
                        <small class="text-muted ms-1">💬</small>
                    </div>`
                ).join('');
                onlineCount.textContent = `${data.online_tables.length}명`;
                
                // 클릭 이벤트 리스너 추가
                const clickableUsers = onlineList.querySelectorAll('.online-user.clickable');
                clickableUsers.forEach(userEl => {
                    userEl.addEventListener('click', function() {
                        const tableId = parseInt(this.dataset.tableId);
                        const nickname = this.dataset.nickname;
                        startPrivateChat(tableId, nickname);
                    });
                });
            }
        }
    } catch (error) {
        console.error('온라인 사용자 로드 오류:', error);
        const onlineList = document.getElementById('online-users-list');
        const onlineCount = document.getElementById('online-count');
        if (onlineList && onlineCount) {
            onlineList.innerHTML = '<div class="online-user">접속자 정보를 불러올 수 없습니다</div>';
            onlineCount.textContent = '0명';
        }
    }
}

// 메시지 전송
async function sendMessage() {
    const messageInput = document.getElementById('message-input');
    const nicknameInput = document.getElementById('nickname-input');
    const sendButton = document.getElementById('send-button');
    
    if (!messageInput || !sendButton) {
        console.error('Required DOM elements not found');
        return;
    }
    
    const message = messageInput.value.trim();
    if (!message) return;
    
    // 디버깅 로그 추가
    console.log('Current table ID:', currentTableId);
    console.log('Message:', message);
    console.log('Is private mode:', isPrivateMode);
    console.log('Target table ID:', targetTableId);
    
    if (!currentTableId) {
        console.error('Table ID is not set');
        alert('테이블 ID가 설정되지 않았습니다. 페이지를 새로고침해주세요.');
        return;
    }
    
    sendButton.disabled = true;
    sendButton.innerHTML = '<div class="spinner-border spinner-border-sm"></div>';
    
    try {
        const formData = new FormData();
        formData.append('table_id', currentTableId.toString());
        formData.append('message', message);
        
        if (nicknameInput) {
            const nickname = nicknameInput.value.trim();
            if (nickname) {
                formData.append('nickname', nickname);
                console.log('Nickname:', nickname);
            }
        }
        
        // 개인 메시지인 경우 target_table_id 추가
        if (isPrivateMode && targetTableId) {
            formData.append('target_table_id', targetTableId.toString());
            console.log('Target table ID:', targetTableId);
        }
        
        // FormData 내용 로깅
        console.log('FormData contents:');
        for (let [key, value] of formData.entries()) {
            console.log(key, value);
        }
        
        const response = await fetch('/chat/send', {
            method: 'POST',
            body: formData
        });
        
        console.log('Response status:', response.status);
        
        if (response.ok) {
            messageInput.value = '';
            loadOnlineUsers(); // 온라인 사용자 목록 업데이트
        } else {
            const errorText = await response.text();
            console.error('Error response:', errorText);
            throw new Error(`메시지 전송 실패: ${response.status}`);
        }
    } catch (error) {
        console.error('메시지 전송 오류:', error);
        alert('메시지 전송에 실패했습니다: ' + error.message);
    } finally {
        sendButton.disabled = false;
        sendButton.innerHTML = '<i class="bi bi-send"></i>';
        messageInput.focus();
    }
}

// 채팅에 메시지 추가
function addMessageToChat(messageData, shouldScroll = true) {
    const chatMessages = document.getElementById('chat-messages');
    if (!chatMessages) return;
    
    // 로딩 메시지 제거
    const loadingElements = chatMessages.querySelectorAll('.loading');
    loadingElements.forEach(el => el.remove());
    
    const isMyMessage = messageData.table_id === currentTableId;
    const isPrivateMessage = messageData.is_private;
    const messageElement = document.createElement('div');
    
    let messageClass = `chat-message ${isMyMessage ? 'my-message' : 'other-message'}`;
    if (isPrivateMessage) {
        messageClass += ' private-message';
    }
    messageElement.className = messageClass;
    
    let headerText = '';
    let messagePrefix = '';
    
    if (isPrivateMessage) {
        // 개인 메시지인 경우
        if (isMyMessage) {
            // 내가 보낸 개인 메시지
            const targetNickname = getTableNickname(messageData.target_table_id);
            headerText = `나 → ${targetNickname} • ${messageData.formatted_time}`;
            messagePrefix = '🔒 ';
        } else {
            // 나에게 온 개인 메시지
            headerText = `${messageData.nickname} → 나 • ${messageData.formatted_time}`;
            messagePrefix = '🔒 ';
        }
    } else {
        // 전체 메시지인 경우
        if (isMyMessage) {
            headerText = `나 • ${messageData.formatted_time}`;
        } else {
            headerText = `${messageData.nickname} • ${messageData.formatted_time}`;
        }
    }
    
    messageElement.innerHTML = `
        <div class="message-header">${headerText}</div>
        <div class="message-content">${messagePrefix}${escapeHtml(messageData.message)}</div>
    `;
    
    chatMessages.appendChild(messageElement);
    
    if (shouldScroll) {
        scrollToBottom();
    }
}

// HTML 이스케이프
function escapeHtml(text) {
    const map = {
        '&': '&amp;',
        '<': '&lt;',
        '>': '&gt;',
        '"': '&quot;',
        "'": '&#039;'
    };
    return text.replace(/[&<>"']/g, function(m) { return map[m]; });
}

// 채팅 스크롤을 맨 아래로
function scrollToBottom() {
    const chatMessages = document.getElementById('chat-messages');
    if (chatMessages) {
        chatMessages.scrollTop = chatMessages.scrollHeight;
    }
}

// ========== 주문 모달 관련 함수들 ==========

// 주문 모달 토글
function toggleOrderModal() {
    const modalElement = document.getElementById('orderModal');
    if (!modalElement) return;
    
    const modal = new bootstrap.Modal(modalElement);
    resetOrderModal();
    loadTablesForOrder();
    modal.show();
}

// 주문 모달 초기화
function resetOrderModal() {
    currentStep = 1;
    selectedTableId = null;
    orderItems = {};
    
    // 모든 단계 숨기기
    document.querySelectorAll('.order-step').forEach(step => {
        step.style.display = 'none';
    });
    
    // 첫 번째 단계 표시
    const firstStep = document.getElementById('step-select-table');
    if (firstStep) {
        firstStep.style.display = 'block';
    }
    
    // 버튼 상태 초기화
    const prevBtn = document.getElementById('prev-btn');
    const nextBtn = document.getElementById('next-btn');
    const submitBtn = document.getElementById('submit-btn');
    
    if (prevBtn) prevBtn.style.display = 'none';
    if (nextBtn) {
        nextBtn.style.display = 'inline-block';
        nextBtn.textContent = '다음';
    }
    if (submitBtn) submitBtn.style.display = 'none';
}

// 주문용 테이블 목록 로드
async function loadTablesForOrder() {
    try {
        const response = await fetch('/chat/online-tables');
        const data = await response.json();
        
        const tableSelection = document.getElementById('table-selection');
        if (!tableSelection) return;
        
        if (!data.online_tables || data.online_tables.length === 0) {
            tableSelection.innerHTML = '<div class="col-12 text-center text-muted">현재 접속 중인 다른 테이블이 없습니다.</div>';
            return;
        }
        
        // 자신의 테이블 제외
        const otherTables = data.online_tables.filter(table => table.table_id !== currentTableId);
        
        if (otherTables.length === 0) {
            tableSelection.innerHTML = '<div class="col-12 text-center text-muted">주문할 수 있는 다른 테이블이 없습니다.</div>';
            return;
        }
        
        tableSelection.innerHTML = otherTables.map(table => `
            <div class="col-md-4 col-sm-6 mb-3">
                <div class="card table-card" data-table-id="${table.table_id}" data-nickname="${table.nickname}" 
                     style="cursor: pointer; transition: all 0.3s;">
                    <div class="card-body text-center">
                        <i class="bi bi-person-circle" style="font-size: 2rem; color: var(--primary-color);"></i>
                        <h6 class="mt-2 mb-0">${table.nickname}</h6>
                        <small class="text-muted">테이블 ${table.table_id}</small>
                    </div>
                </div>
            </div>
        `).join('');
        
        // 테이블 선택 이벤트 리스너 추가
        const tableCards = tableSelection.querySelectorAll('.table-card');
        tableCards.forEach(card => {
            card.addEventListener('click', function() {
                const tableId = parseInt(this.dataset.tableId);
                const nickname = this.dataset.nickname;
                selectTable(tableId, nickname, this);
            });
        });
        
    } catch (error) {
        console.error('테이블 목록 로드 오류:', error);
        const tableSelection = document.getElementById('table-selection');
        if (tableSelection) {
            tableSelection.innerHTML = '<div class="col-12 text-center text-danger">테이블 목록을 불러올 수 없습니다.</div>';
        }
    }
}

// 테이블 선택
function selectTable(tableId, nickname, cardElement) {
    selectedTableId = tableId;
    
    // 모든 테이블 카드에서 선택 상태 제거
    document.querySelectorAll('.table-card').forEach(card => {
        card.classList.remove('border-primary');
        card.style.backgroundColor = '';
    });
    
    // 선택된 테이블 카드 하이라이트
    cardElement.classList.add('border-primary');
    cardElement.style.backgroundColor = 'var(--light-color)';
    
    // 다음 버튼 활성화
    const nextBtn = document.getElementById('next-btn');
    if (nextBtn) {
        nextBtn.disabled = false;
    }
}

// 다음 단계
function nextStep() {
    if (currentStep === 1) {
        if (!selectedTableId) {
            alert('테이블을 선택해주세요.');
            return;
        }
        loadMenuForOrder();
        currentStep = 2;
        showStep(2);
    } else if (currentStep === 2) {
        if (Object.keys(orderItems).length === 0) {
            alert('최소 하나의 메뉴를 선택해주세요.');
            return;
        }
        currentStep = 3;
        showStep(3);
        updateFinalInfo();
    }
}

// 이전 단계
function previousStep() {
    if (currentStep > 1) {
        currentStep--;
        showStep(currentStep);
    }
}

// 단계 표시
function showStep(step) {
    // 모든 단계 숨기기
    document.querySelectorAll('.order-step').forEach(stepEl => {
        stepEl.style.display = 'none';
    });
    
    // 선택된 단계 표시
    const stepEl = document.getElementById(`step-${step === 1 ? 'select-table' : step === 2 ? 'select-menu' : 'add-message'}`);
    if (stepEl) {
        stepEl.style.display = 'block';
    }
    
    // 버튼 상태 업데이트
    const prevBtn = document.getElementById('prev-btn');
    const nextBtn = document.getElementById('next-btn');
    const submitBtn = document.getElementById('submit-btn');
    
    if (prevBtn) prevBtn.style.display = step > 1 ? 'inline-block' : 'none';
    if (nextBtn) nextBtn.style.display = step < 3 ? 'inline-block' : 'none';
    if (submitBtn) submitBtn.style.display = step === 3 ? 'inline-block' : 'none';
}

// 메뉴 로드
async function loadMenuForOrder() {
    try {
        const response = await fetch('/api/menu-data');
        menuData = await response.json();
        
        const selectedTable = document.querySelector('.table-card.border-primary h6');
        const selectedTableInfo = document.getElementById('selected-table-info');
        
        if (selectedTable && selectedTableInfo) {
            selectedTableInfo.textContent = `→ ${selectedTable.textContent}에게 주문`;
        }
        
        renderMenuCategories();
        
    } catch (error) {
        console.error('메뉴 로드 오류:', error);
        const menuCategories = document.getElementById('menu-categories');
        if (menuCategories) {
            menuCategories.innerHTML = '<div class="alert alert-danger">메뉴를 불러올 수 없습니다.</div>';
        }
    }
}

// 메뉴 카테고리 렌더링
function renderMenuCategories() {
    const menuCategories = document.getElementById('menu-categories');
    if (!menuCategories) return;
    
    if (!menuData.menu_items) {
        menuCategories.innerHTML = '<div class="alert alert-warning">메뉴 데이터가 없습니다.</div>';
        return;
    }
    
    const categories = ['main_dishes', 'set_menu', 'drinks'];
    const categoryNames = {
        'main_dishes': '메인 요리',
        'set_menu': '세트 메뉴', 
        'drinks': '음료'
    };
    
    menuCategories.innerHTML = categories.map(category => {
        const items = Object.values(menuData.menu_items).filter(item => item.category === category);
        if (items.length === 0) return '';
        
        return `
            <div class="mb-4">
                <h6 class="text-primary">${categoryNames[category]}</h6>
                <div class="row">
                    ${items.map(item => `
                        <div class="col-md-6 mb-2">
                            <div class="card menu-item-card" data-item-id="${item.id}" style="cursor: pointer;">
                                <div class="card-body p-3">
                                    <div class="d-flex justify-content-between align-items-start">
                                        <div>
                                            <h6 class="mb-1">${item.name_kr}</h6>
                                            <small class="text-muted">${item.description || ''}</small>
                                            <div class="mt-1">
                                                <strong>${item.price.toLocaleString()}원</strong>
                                            </div>
                                        </div>
                                        <div class="quantity-controls" id="controls-${item.id}" style="display: none;">
                                            <button class="btn btn-sm btn-outline-primary quantity-minus" data-item-id="${item.id}">-</button>
                                            <span class="mx-2" id="qty-${item.id}">1</span>
                                            <button class="btn btn-sm btn-outline-primary quantity-plus" data-item-id="${item.id}">+</button>
                                        </div>
                                    </div>
                                </div>
                            </div>
                        </div>
                    `).join('')}
                </div>
            </div>
        `;
    }).join('');
    
    // 메뉴 아이템 이벤트 리스너 추가
    setupMenuEventListeners();
}

// 메뉴 이벤트 리스너 설정
function setupMenuEventListeners() {
    const menuCategories = document.getElementById('menu-categories');
    if (!menuCategories) return;
    
    // 메뉴 아이템 클릭 이벤트
    const menuCards = menuCategories.querySelectorAll('.menu-item-card');
    menuCards.forEach(card => {
        card.addEventListener('click', function() {
            const itemId = this.dataset.itemId;
            toggleMenuItem(itemId);
        });
    });
    
    // 수량 조절 버튼 이벤트
    const minusButtons = menuCategories.querySelectorAll('.quantity-minus');
    const plusButtons = menuCategories.querySelectorAll('.quantity-plus');
    
    minusButtons.forEach(btn => {
        btn.addEventListener('click', function(e) {
            e.stopPropagation();
            const itemId = this.dataset.itemId;
            changeQuantity(itemId, -1);
        });
    });
    
    plusButtons.forEach(btn => {
        btn.addEventListener('click', function(e) {
            e.stopPropagation();
            const itemId = this.dataset.itemId;
            changeQuantity(itemId, 1);
        });
    });
}

// 메뉴 아이템 토글
function toggleMenuItem(itemId) {
    const controlsEl = document.getElementById(`controls-${itemId}`);
    const qtyEl = document.getElementById(`qty-${itemId}`);
    const cardEl = document.querySelector(`[data-item-id="${itemId}"]`);
    
    if (!controlsEl || !qtyEl || !cardEl) return;
    
    if (orderItems[itemId]) {
        delete orderItems[itemId];
        controlsEl.style.display = 'none';
        cardEl.classList.remove('border-primary');
    } else {
        orderItems[itemId] = 1;
        controlsEl.style.display = 'block';
        qtyEl.textContent = '1';
        cardEl.classList.add('border-primary');
    }
    
    updateOrderSummary();
}

// 수량 변경
function changeQuantity(itemId, change) {
    if (!orderItems[itemId]) return;
    
    const controlsEl = document.getElementById(`controls-${itemId}`);
    const qtyEl = document.getElementById(`qty-${itemId}`);
    const cardEl = document.querySelector(`[data-item-id="${itemId}"]`);
    
    if (!controlsEl || !qtyEl || !cardEl) return;
    
    orderItems[itemId] += change;
    
    if (orderItems[itemId] <= 0) {
        delete orderItems[itemId];
        controlsEl.style.display = 'none';
        cardEl.classList.remove('border-primary');
    } else {
        qtyEl.textContent = orderItems[itemId];
    }
    
    updateOrderSummary();
}

// 주문 요약 업데이트
function updateOrderSummary() {
    const summaryDiv = document.getElementById('order-summary');
    const totalAmountSpan = document.getElementById('total-amount');
    
    if (!summaryDiv || !totalAmountSpan) return;
    
    if (Object.keys(orderItems).length === 0) {
        summaryDiv.innerHTML = '<p class="text-muted mb-0">아직 선택된 메뉴가 없습니다.</p>';
        totalAmountSpan.textContent = '0';
        return;
    }
    
    let totalAmount = 0;
    const summaryHtml = Object.entries(orderItems).map(([itemId, quantity]) => {
        const item = menuData.menu_items[itemId];
        if (!item) return '';
        
        const itemTotal = item.price * quantity;
        totalAmount += itemTotal;
        
        return `
            <div class="d-flex justify-content-between align-items-center mb-2">
                <div>
                    <strong>${item.name_kr}</strong>
                    <small class="text-muted"> x ${quantity}</small>
                </div>
                <span>${itemTotal.toLocaleString()}원</span>
            </div>
        `;
    }).join('');
    
    summaryDiv.innerHTML = summaryHtml;
    totalAmountSpan.textContent = totalAmount.toLocaleString();
}

// 최종 정보 업데이트
function updateFinalInfo() {
    const selectedTableNickname = document.querySelector('.table-card.border-primary h6');
    const finalTableInfo = document.getElementById('final-table-info');
    
    if (selectedTableNickname && finalTableInfo) {
        finalTableInfo.textContent = selectedTableNickname.textContent;
    }
}

// 주문 제출
async function submitGiftOrder() {
    const submitBtn = document.getElementById('submit-btn');
    if (!submitBtn) return;
    
    const originalText = submitBtn.innerHTML;
    
    submitBtn.disabled = true;
    submitBtn.innerHTML = '<div class="spinner-border spinner-border-sm me-2"></div>주문 중...';
    
    try {
        const orderMessageEl = document.getElementById('order-message');
        const orderMessage = orderMessageEl ? orderMessageEl.value.trim() : '';
        
        const response = await fetch('/chat/gift-order', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({
                from_table_id: currentTableId,
                to_table_id: selectedTableId,
                menu: orderItems,
                message: orderMessage || null
            })
        });
        
        if (response.ok) {
            const result = await response.json();
            
            // 모달 닫기
            const modalEl = document.getElementById('orderModal');
            if (modalEl && bootstrap.Modal.getInstance(modalEl)) {
                bootstrap.Modal.getInstance(modalEl).hide();
            }
            
            // 성공 메시지 표시
            alert(`주문이 성공적으로 완료되었습니다! 🎉\n주문 번호: ${result.order_id}`);
            
            // 채팅에 주문 알림 메시지 자동 전송
            if (orderMessage) {
                setTimeout(() => {
                    const messageInput = document.getElementById('message-input');
                    if (messageInput) {
                        messageInput.value = orderMessage;
                        sendMessage();
                    }
                }, 1000);
            }
            
        } else {
            throw new Error('주문 처리 중 오류가 발생했습니다.');
        }
        
    } catch (error) {
        console.error('주문 오류:', error);
        alert('주문 처리 중 오류가 발생했습니다. 다시 시도해주세요.');
    } finally {
        submitBtn.disabled = false;
        submitBtn.innerHTML = originalText;
    }
}

// ========== 선물 알림 관련 함수들 ==========

// 선물 주문 알림 처리
function handleGiftOrderNotification(data) {
    // 받는 사람에게만 표시
    if (data.to_table_id === currentTableId) {
        showGiftOrderAlert(data);
    }
}

// 선물 주문 공지 처리 (전체 채팅에 표시)
function handleGiftAnnouncement(data) {
    const systemMessage = {
        type: "system_message",
        message: `🎁 ${data.from_nickname}님이 ${data.to_nickname}님에게 ${data.amount.toLocaleString()}원의 주문을 선물했습니다!`,
        formatted_time: new Date().toLocaleString('ko-KR', {
            timeZone: 'Asia/Seoul',
            year: 'numeric',
            month: '2-digit',
            day: '2-digit',
            hour: '2-digit',
            minute: '2-digit'
        }),
        nickname: "시스템"
    };
    
    addSystemMessageToChat(systemMessage);
}

// 선물 주문 알림 모달 표시
function showGiftOrderAlert(data) {
    const alertHtml = `
        <div class="modal fade" id="giftOrderAlert" tabindex="-1" aria-hidden="true">
            <div class="modal-dialog">
                <div class="modal-content">
                    <div class="modal-header bg-success text-white">
                        <h5 class="modal-title">
                            🎁 선물이 도착했습니다!
                        </h5>
                        <button type="button" class="btn-close btn-close-white" data-bs-dismiss="modal"></button>
                    </div>
                    <div class="modal-body text-center">
                        <div class="mb-3">
                            <i class="bi bi-gift" style="font-size: 3rem; color: var(--success-color);"></i>
                        </div>
                        <h6 class="mb-3">${data.from_nickname}님이 주문을 선물해주셨습니다!</h6>
                        
                        <div class="card">
                            <div class="card-header">
                                <strong>주문 내역</strong>
                            </div>
                            <div class="card-body">
                                ${data.menu_items.map(item => `<div>${item}</div>`).join('')}
                                <hr>
                                <strong>총 금액: ${data.amount.toLocaleString()}원</strong>
                            </div>
                        </div>
                        
                        ${data.message ? `
                            <div class="mt-3">
                                <small class="text-muted">메시지:</small>
                                <div class="alert alert-info">${data.message}</div>
                            </div>
                        ` : ''}
                        
                        <div class="mt-3">
                            <small class="text-muted">주문 번호: #${data.order_id}</small>
                        </div>
                    </div>
                    <div class="modal-footer">
                        <button type="button" class="btn btn-primary" data-bs-dismiss="modal">
                            <i class="bi bi-heart me-1"></i>감사합니다!
                        </button>
                    </div>
                </div>
            </div>
        </div>
    `;
    
    // 기존 알림 모달 제거
    const existingAlert = document.getElementById('giftOrderAlert');
    if (existingAlert) {
        existingAlert.remove();
    }
    
    // 새 알림 모달 추가
    document.body.insertAdjacentHTML('beforeend', alertHtml);
    
    // 모달 표시
    const alertEl = document.getElementById('giftOrderAlert');
    if (alertEl) {
        const modal = new bootstrap.Modal(alertEl);
        modal.show();
        
        // 모달이 닫힌 후 DOM에서 제거
        alertEl.addEventListener('hidden.bs.modal', function() {
            this.remove();
        });
    }
}

// 시스템 메시지를 채팅에 추가
function addSystemMessageToChat(messageData) {
    const chatMessages = document.getElementById('chat-messages');
    if (!chatMessages) return;
    
    const messageElement = document.createElement('div');
    messageElement.className = 'chat-message system-message';
    messageElement.style.cssText = `
        background: linear-gradient(135deg, var(--success-color), var(--info-color));
        color: var(--dark-color);
        text-align: center;
        margin: 1rem auto;
        max-width: 90%;
        font-weight: 500;
        border: 2px solid var(--border-color);
    `;
    
    messageElement.innerHTML = `
        <div class="message-content">${messageData.message}</div>
        <div class="message-header" style="opacity: 0.8; margin-top: 0.3rem;">
            ${messageData.formatted_time}
        </div>
    `;
    
    chatMessages.appendChild(messageElement);
    scrollToBottom();
}

// 테이블 ID로 닉네임 가져오기 (온라인 사용자 목록에서)
function getTableNickname(tableId) {
    const onlineList = document.getElementById('online-users-list');
    if (!onlineList) return `테이블${tableId}`;
    
    // 온라인 사용자 목록에서 해당 테이블의 닉네임 찾기
    const userElements = onlineList.querySelectorAll('.online-user');
    for (let userEl of userElements) {
        if (userEl.dataset.tableId == tableId) {
            return userEl.textContent;
        }
    }
    
    return `테이블${tableId}`;
}

// 개인 메시지 시작
function startPrivateChat(tableId, nickname) {
    isPrivateMode = true;
    targetTableId = tableId;
    targetNickname = nickname;
    updateChatModeUI();
    console.log('Private chat started with tableId:', tableId, 'and nickname:', nickname);
}

// 전체 채팅으로 돌아가기
function stopPrivateChat() {
    isPrivateMode = false;
    targetTableId = null;
    targetNickname = null;
    updateChatModeUI();
    console.log('Switched back to public chat');
}

// 채팅 모드 UI 업데이트
function updateChatModeUI() {
    const messageInput = document.getElementById('message-input');
    const chatHeader = document.querySelector('.chat-container .d-flex');
    
    if (!messageInput) return;
    
    if (isPrivateMode && targetNickname) {
        messageInput.placeholder = `${targetNickname}님에게 개인 메시지...`;
        
        // 개인 메시지 모드 표시
        let privateModeIndicator = document.getElementById('private-mode-indicator');
        if (!privateModeIndicator) {
            privateModeIndicator = document.createElement('div');
            privateModeIndicator.id = 'private-mode-indicator';
            privateModeIndicator.className = 'private-mode-indicator';
            
            // 채팅 컨테이너 위에 추가
            const chatContainer = document.querySelector('.chat-container');
            if (chatContainer) {
                chatContainer.insertBefore(privateModeIndicator, chatContainer.firstChild);
            }
        }
        
        privateModeIndicator.innerHTML = `
            <div class="alert alert-info d-flex justify-content-between align-items-center m-0">
                <span>🔒 <strong>${targetNickname}</strong>님과 개인 대화 중</span>
                <button class="btn btn-sm btn-outline-secondary" onclick="stopPrivateChat()">
                    전체 채팅으로 돌아가기
                </button>
            </div>
        `;
        privateModeIndicator.style.display = 'block';
    } else {
        messageInput.placeholder = '메시지를 입력하세요...';
        
        // 개인 메시지 모드 표시 제거
        const privateModeIndicator = document.getElementById('private-mode-indicator');
        if (privateModeIndicator) {
            privateModeIndicator.style.display = 'none';
        }
    }
}

// 페이지 종료 시 정리
window.addEventListener('beforeunload', function() {
    if (websocket && websocket.readyState === WebSocket.OPEN) {
        websocket.close();
    }
    
    if (window.messagePollingInterval) {
        clearInterval(window.messagePollingInterval);
        window.messagePollingInterval = null;
    }
});

// 페이지 로드 시 자동 초기화
document.addEventListener('DOMContentLoaded', function() {
    console.log('DOMContentLoaded event fired');
    
    const container = document.getElementById('chat-container');
    console.log('Chat container element:', container);
    
    if (!container) {
        console.error('Chat container element not found');
        return;
    }
    
    // 이벤트 리스너 추가
    setupEventListeners();
    
    const hasTableIdAttr = container.hasAttribute('data-table-id');
    console.log('Has data-table-id attribute:', hasTableIdAttr);
    
    if (hasTableIdAttr) {
        const tableId = container.getAttribute('data-table-id');
        console.log('Table ID from data attribute:', tableId);
        console.log('Table ID type:', typeof tableId);
        console.log('Table ID length:', tableId ? tableId.length : 'N/A');
        
        if (tableId && tableId.trim() !== '') {
            console.log('Calling initializeChat with table ID:', tableId);
            // 테이블 ID가 있는 경우 채팅 초기화
            initializeChat(tableId);
        } else {
            console.error('data-table-id attribute exists but is empty');
        }
    } else {
        console.log('No data-table-id attribute found, calling initializeTableInput');
        // 테이블 ID가 없는 경우 입력 폼 초기화
        initializeTableInput();
    }
});

// 이벤트 리스너 설정
function setupEventListeners() {
    console.log('Setting up event listeners');
    
    // 채팅 입장 버튼
    const joinChatBtn = document.getElementById('join-chat-btn');
    if (joinChatBtn) {
        joinChatBtn.addEventListener('click', joinChat);
        console.log('Join chat button event listener added');
    }
    
    // 메시지 전송 버튼
    const sendButton = document.getElementById('send-button');
    if (sendButton) {
        sendButton.addEventListener('click', sendMessage);
        console.log('Send message button event listener added');
    }
    
    // 주문 모달 토글 버튼
    const toggleOrderBtn = document.getElementById('toggle-order-btn');
    if (toggleOrderBtn) {
        toggleOrderBtn.addEventListener('click', toggleOrderModal);
        console.log('Toggle order modal button event listener added');
    }
    
    // 모달 네비게이션 버튼들
    const prevBtn = document.getElementById('prev-btn');
    if (prevBtn) {
        prevBtn.addEventListener('click', previousStep);
        console.log('Previous step button event listener added');
    }
    
    const nextBtn = document.getElementById('next-btn');
    if (nextBtn) {
        nextBtn.addEventListener('click', nextStep);
        console.log('Next step button event listener added');
    }
    
    const submitBtn = document.getElementById('submit-btn');
    if (submitBtn) {
        submitBtn.addEventListener('click', submitGiftOrder);
        console.log('Submit order button event listener added');
    }
} 