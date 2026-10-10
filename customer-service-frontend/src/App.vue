<script setup>
import { computed, nextTick, onMounted, onUnmounted, ref, watch } from 'vue'
import xiaoerAvatar from './assets/xiaoer.png'
import userProfileAvatar from './assets/userProfileAvatar.svg'

// ── 基础状态 ──────────────────────────────────────────────
const senderId = ref('u1001')
const draftMessage = ref('')
const isSending = ref(false)
const errorMessage = ref('')
const messages = ref([])
const messagesContainer = ref(null)

const orders = ref([])
const products = ref([])
const isLoadingSidebar = ref(false)
const sidebarError = ref('')
const activeTab = ref('orders')

// ── 新增功能状态 ──────────────────────────────────────────
// 1. 主题切换
const theme = ref(localStorage.getItem('chat-theme') || 'light')
function toggleTheme() {
  theme.value = theme.value === 'light' ? 'dark' : 'light'
  localStorage.setItem('chat-theme', theme.value)
}

// 2. 快捷回复模板
const quickReplies = [
  { label: '查订单', text: '帮我查一下订单状态' },
  { label: '查物流', text: '我的快递到哪了' },
  { label: '申请退款', text: '我要申请退款' },
  { label: '转人工', text: '转人工客服' },
  { label: '商品咨询', text: '想了解一下这个商品' },
]
const showQuickReplies = ref(true)

// 3. 订单状态筛选
const orderStatusFilter = ref('all')
const orderStatusOptions = [
  { value: 'all', label: '全部' },
  { value: '待发货', label: '待发货' },
  { value: '待揽收', label: '待揽收' },
  { value: '运输中', label: '运输中' },
  { value: '已完成', label: '已完成' },
  { value: '已取消', label: '已取消' },
]
const filteredOrders = computed(() => {
  if (orderStatusFilter.value === 'all') return orders.value
  return orders.value.filter(o => o.status === orderStatusFilter.value)
})

// 4. 字符计数
const charCount = computed(() => draftMessage.value.length)
const maxChars = 500

// 5. 回到底部按钮
const showScrollBottom = ref(false)
function onMessagesScroll() {
  const container = messagesContainer.value
  if (!container) return
  const distFromBottom = container.scrollHeight - container.scrollTop - container.clientHeight
  showScrollBottom.value = distFromBottom > 200
}
async function scrollToBottomSmooth() {
  await nextTick()
  const container = messagesContainer.value
  if (container) container.scrollTo({ top: container.scrollHeight, behavior: 'smooth' })
}

// 6. 导出对话
function exportConversation() {
  const lines = []
  lines.push('═══════════════════════════════════════')
  lines.push(`  电商客服对话记录`)
  lines.push(`  用户: ${senderId.value}`)
  lines.push(`  导出时间: ${new Date().toLocaleString('zh-CN')}`)
  lines.push(`  消息总数: ${messages.value.length}`)
  lines.push('═══════════════════════════════════════')
  lines.push('')
  for (const msg of messages.value) {
    if (msg.type === 'divider') {
      lines.push(`── ${msg.text} ──`)
      continue
    }
    const time = msg.timestamp ? new Date(msg.timestamp).toLocaleTimeString('zh-CN') : ''
    const role = msg.role === 'user' ? '【用户】' : '【客服】'
    if (msg.type === 'text') {
      lines.push(`${role} ${time}`)
      lines.push(`  ${msg.text}`)
      lines.push('')
    } else if (msg.type === 'object') {
      const payload = msg.payload || {}
      lines.push(`${role} ${time} [${msg.objectType === 'order' ? '订单卡片' : '商品卡片'}]`)
      lines.push(`  ${payload.title || payload.order_id || payload.product_id || ''}`)
      lines.push('')
    }
  }
  const blob = new Blob([lines.join('\n')], { type: 'text/plain;charset=utf-8' })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = `对话记录_${senderId.value}_${new Date().toISOString().slice(0, 10)}.txt`
  a.click()
  URL.revokeObjectURL(url)
}

// 7. 对话统计
const conversationStats = computed(() => {
  const userMsgs = messages.value.filter(m => m.role === 'user' && m.type !== 'divider')
  const botMsgs = messages.value.filter(m => m.role === 'bot' && m.type !== 'divider')
  return {
    total: messages.value.filter(m => m.type !== 'divider').length,
    userCount: userMsgs.length,
    botCount: botMsgs.length,
  }
})

// ── TTS state ──────────────────────────────────────────────
const ttsState = ref({})
let currentAudio = null

// Copy state
const copyState = ref({})

// ── 魔珐星云数字人（具身驱动 SDK JS 版）接入 ──────────────────────────
const XMOV_SDK_URL = 'https://media.xingyun3d.com/xingyun3d/general/litesdk/xmovAvatar@latest.js'
const XMOV_GATEWAY = 'https://nebula-agent.xingyun3d.com/user/v1/ttsa/session'

const avatarStatus = ref('offline')
const avatarAppId = ref('')
const avatarAppSecret = ref('')
const avatarError = ref('')
const avatarDownloadProgress = ref(0)
const avatarSpeaking = ref(false)
const avatarCurrentText = ref('')

let avatarSdk = null
let avatarSdkLoadPromise = null
const avatarSpeakQueue = []
let avatarSpeakLooping = false
let avatarVoiceEndResolve = null

const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms))

function loadXmovSdk() {
  if (window.XmovAvatar) return Promise.resolve()
  if (avatarSdkLoadPromise) return avatarSdkLoadPromise
  avatarSdkLoadPromise = new Promise((resolve, reject) => {
    const script = document.createElement('script')
    script.src = XMOV_SDK_URL
    script.async = true
    script.onload = () => resolve()
    script.onerror = () => {
      avatarSdkLoadPromise = null
      reject(new Error('数字人 SDK 脚本加载失败，请检查网络后重试。'))
    }
    document.head.appendChild(script)
  })
  return avatarSdkLoadPromise
}

function resolveAvatarVoiceEnd() {
  if (avatarVoiceEndResolve) {
    const resolve = avatarVoiceEndResolve
    avatarVoiceEndResolve = null
    resolve()
  }
}

function waitAvatarVoiceEnd(text) {
  const timeoutMs = Math.min(90000, 8000 + text.length * 220)
  return new Promise((resolve) => {
    let done = false
    const finish = () => {
      if (done) return
      done = true
      avatarVoiceEndResolve = null
      clearTimeout(timer)
      resolve()
    }
    avatarVoiceEndResolve = finish
    const timer = setTimeout(finish, timeoutMs)
  })
}

function enqueueAvatarSpeech(botMessages) {
  if (avatarStatus.value !== 'connected' || !avatarSdk) return
  for (const message of botMessages) {
    if (message.object) continue
    const text = (message.text || '').trim()
    if (!text) continue
    avatarSpeakQueue.push(text.slice(0, 500))
  }
  if (avatarSpeakQueue.length) drainAvatarSpeakQueue()
}

async function drainAvatarSpeakQueue() {
  if (avatarSpeakLooping) return
  avatarSpeakLooping = true
  while (avatarSpeakQueue.length && avatarSdk && avatarStatus.value === 'connected') {
    const text = avatarSpeakQueue.shift()
    avatarCurrentText.value = text
    avatarSpeaking.value = true
    const waiter = waitAvatarVoiceEnd(text)
    try {
      avatarSdk.speak(text, true, true)
    } catch (error) {
      console.error('[avatar] speak 调用失败:', error)
    }
    await waiter
    avatarSpeaking.value = false
    try {
      if (typeof avatarSdk.interactiveidle === 'function') avatarSdk.interactiveidle()
      else if (typeof avatarSdk.interactiveIdle === 'function') avatarSdk.interactiveIdle()
      else if (typeof avatarSdk.idle === 'function') avatarSdk.idle()
    } catch (error) {
      console.error('[avatar] interactive_idle 切换失败:', error)
    }
    await sleep(400)
  }
  avatarCurrentText.value = ''
  avatarSpeakLooping = false
}

function destroyAvatarSdk() {
  if (avatarSdk) {
    try { avatarSdk.destroy() } catch (error) { console.error('[avatar] destroy 失败:', error) }
    avatarSdk = null
  }
  avatarSpeakQueue.length = 0
  avatarSpeakLooping = false
  resolveAvatarVoiceEnd()
  avatarSpeaking.value = false
  avatarCurrentText.value = ''
}

async function connectAvatar() {
  const appId = avatarAppId.value.trim()
  const appSecret = avatarAppSecret.value.trim()
  avatarError.value = ''
  if (!appId || !appSecret) {
    avatarError.value = '请先填写魔珐星云驱动应用的 App ID 和 App Secret。'
    return
  }
  if (!window.isSecureContext && !['localhost', '127.0.0.1'].includes(location.hostname)) {
    avatarError.value = '官方 SDK 仅支持 localhost 或 HTTPS 访问，请通过 http://localhost:5173 打开本页。'
    return
  }
  avatarStatus.value = 'connecting'
  avatarDownloadProgress.value = 0
  try { await loadXmovSdk() } catch (error) {
    avatarStatus.value = 'error'
    avatarError.value = error instanceof Error ? error.message : 'SDK 加载失败。'
    return
  }
  try {
    const XmovAvatar = window.XmovAvatar
    avatarSdk = new XmovAvatar({
      containerId: '#xmov-avatar-sdk',
      appId, appSecret,
      gatewayServer: XMOV_GATEWAY,
      hardwareAcceleration: 'prefer-hardware',
      enableLogger: false,
      onMessage(message) {
        if (message && typeof message.code === 'number' && message.code !== 0) {
          avatarError.value = `数字人异常（${message.code}）：${message.message || '未知错误'}`
        }
      },
      onVoiceStateChange(status) {
        if (status === 'start') avatarSpeaking.value = true
        if (status === 'end') { avatarSpeaking.value = false; resolveAvatarVoiceEnd() }
      },
      onStatusChange(status) { console.log('[avatar] SDK status:', status) },
    })
    const initResult = avatarSdk.init({
      onDownloadProgress(progress) {
        avatarDownloadProgress.value = Math.round(progress ?? 0)
        if ((progress ?? 0) >= 100 && avatarStatus.value === 'connecting') avatarStatus.value = 'connected'
      },
    })
    if (initResult && typeof initResult.then === 'function') await initResult
    if (avatarStatus.value === 'connecting') avatarStatus.value = 'connected'
  } catch (error) {
    destroyAvatarSdk()
    avatarStatus.value = 'error'
    avatarError.value = error instanceof Error ? error.message : '数字人初始化失败，请检查 App ID / App Secret。'
  }
}

function disconnectAvatar() {
  destroyAvatarSdk()
  avatarError.value = ''
  avatarStatus.value = 'offline'
}

// ── 客服 & 用户配置 ──────────────────────────────────────
const customerService = { name: '小宝', title: '金牌客服', avatar: xiaoerAvatar, status: '在线' }
const userProfile = { name: '你', avatar: userProfileAvatar }

// ── Turn 结构 ──────────────────────────────────────────────
const turns = computed(() => {
  const result = []
  let currentTurn = null
  let turnIndex = 0
  for (const message of messages.value) {
    if (message.type === 'divider') {
      if (currentTurn) { result.push(currentTurn); currentTurn = null }
      result.push({ type: 'divider', text: message.text })
      continue
    }
    if (message.role === 'user') {
      if (currentTurn) result.push(currentTurn)
      turnIndex++
      currentTurn = { type: 'turn', id: `turn-${turnIndex}`, index: turnIndex, userMessage: message, botMessages: [] }
    } else if (message.role === 'bot') {
      if (!currentTurn) {
        turnIndex++
        currentTurn = { type: 'turn', id: `turn-${turnIndex}`, index: turnIndex, userMessage: null, botMessages: [] }
      }
      currentTurn.botMessages.push(message)
    }
  }
  if (currentTurn) result.push(currentTurn)
  return result
})

// ── API 端点 ──────────────────────────────────────────────
const chatEndpoint = computed(() => '/api/chat')
const chatHistoryEndpoint = computed(() => `/api/chat/history?sender_id=${encodeURIComponent(senderId.value.trim())}`)
const commerceOrdersEndpoint = computed(() => `/commerce/users/${encodeURIComponent(senderId.value.trim())}/orders`)
const commerceProductsEndpoint = computed(() => `/commerce/users/${encodeURIComponent(senderId.value.trim())}/products`)

// ── 消息操作 ──────────────────────────────────────────────
function createBaseMessage(role) {
  return { id: crypto.randomUUID(), role, buttons: [], timestamp: Date.now() }
}

function appendUserText(text) {
  messages.value.push({ ...createBaseMessage('user'), type: 'text', text })
}

function appendUserObject(objectType, payload) {
  messages.value.push({ ...createBaseMessage('user'), type: 'object', objectType, payload })
}

function appendBotMessages(botMessages) {
  for (const message of botMessages) appendMessage('bot', message)
}

function appendMessage(role, message) {
  if (role === 'divider') {
    messages.value.push({ ...createBaseMessage('divider'), type: 'divider', text: message.text ?? '以上为历史消息' })
    return
  }
  if (message.object) {
    messages.value.push({ ...createBaseMessage(role), type: 'object', objectType: message.object.type, payload: message.object })
  } else {
    messages.value.push({ ...createBaseMessage(role), type: 'text', text: message.text ?? '', suggestions: message.suggestions ?? null })
  }
}

function setHistoryMessages(historyMessages) {
  messages.value = []
  for (const message of historyMessages) {
    const role = ['user', 'bot', 'divider'].includes(message.role) ? message.role : 'bot'
    appendMessage(role, message)
  }
}

async function scrollToBottom() {
  await nextTick()
  const container = messagesContainer.value
  if (!container) return
  container.scrollTop = container.scrollHeight
}

watch(() => messages.value.length, async () => { await scrollToBottom() })

function resetConversation() {
  messages.value = []
  errorMessage.value = ''
}

function formatAmount(amount) {
  const n = Number(amount)
  return Number.isNaN(n) ? '￥0.00' : `￥${n.toFixed(2)}`
}

function formatTime(ts) {
  if (!ts) return ''
  const d = new Date(ts)
  return d.toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' })
}

const ORDER_STATUS_CLASS = {
  '待发货': 'status-warning', '待揽收': 'status-warning',
  '运输中': 'status-info', '派送中': 'status-info',
  '已完成': 'status-success', '已签收': 'status-success',
  '已取消': 'status-muted', '退款中': 'status-danger', '已退款': 'status-muted',
}

function getStatusClass(status) { return ORDER_STATUS_CLASS[status] || 'status-muted' }

function formatProductSummary(product) {
  if (product.description) return product.description
  if (product.attributes?.price) return `商品价格：${formatAmount(product.attributes.price)}`
  return '商品信息'
}

function getObjectTitle(message) {
  const p = message.payload ?? {}
  return p.title || (message.objectType === 'order' ? '订单对象' : '商品对象')
}

function getObjectIdentifier(message) {
  const p = message.payload ?? {}
  const id = p.order_id ?? p.product_id ?? p.id
  const label = message.objectType === 'order' ? '订单号' : '商品号'
  return id ? `${label}：${id}` : label
}

function getObjectSummary(message) {
  const p = message.payload ?? {}
  if (message.objectType === 'order') {
    const status = p.status ?? p.attributes?.status
    return status ? `订单状态：${status}` : '订单'
  }
  return formatProductSummary(p)
}

function getObjectAmount(message) {
  const p = message.payload ?? {}
  const amount = message.objectType === 'order' ? (p.amount ?? p.attributes?.amount) : (p.price ?? p.attributes?.price)
  return formatAmount(amount)
}

// ── 数据获取 ──────────────────────────────────────────────
async function fetchSidebarData() {
  const sid = senderId.value.trim()
  orders.value = []
  products.value = []
  sidebarError.value = ''
  if (!sid) return
  isLoadingSidebar.value = true
  try {
    const [ordersRes, productsRes] = await Promise.all([fetch(commerceOrdersEndpoint.value), fetch(commerceProductsEndpoint.value)])
    const [ordersPayload, productsPayload] = await Promise.all([ordersRes.json(), productsRes.json()])
    if (!ordersRes.ok) throw new Error(ordersPayload.detail || '加载订单列表失败。')
    if (!productsRes.ok) throw new Error(productsPayload.detail || '加载商品列表失败。')
    orders.value = Array.isArray(ordersPayload?.data?.orders) ? ordersPayload.data.orders : []
    products.value = Array.isArray(productsPayload?.data?.products) ? productsPayload.data.products : []
  } catch (error) {
    sidebarError.value = error instanceof Error ? error.message : '加载右侧列表失败。'
  } finally {
    isLoadingSidebar.value = false
  }
}

async function fetchChatHistory() {
  const sid = senderId.value.trim()
  if (!sid) { messages.value = []; return }
  try {
    const response = await fetch(chatHistoryEndpoint.value)
    const data = await response.json()
    if (!response.ok) throw new Error(data.detail || '加载历史消息失败。')
    if (sid === senderId.value.trim()) setHistoryMessages(Array.isArray(data?.messages) ? data.messages : [])
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '加载历史消息失败。'
  }
}

// ── 发送消息 ──────────────────────────────────────────────
async function sendPayload(payload) {
  if (isSending.value) return
  errorMessage.value = ''
  isSending.value = true
  try {
    const response = await fetch(chatEndpoint.value, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ sender_id: senderId.value.trim(), ...payload }),
    })
    const data = await response.json()
    if (!response.ok) throw new Error(data.detail || '请求失败。')
    const botMessages = data.messages ?? []
    appendBotMessages(botMessages)
    enqueueAvatarSpeech(botMessages)
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '请求失败。'
  } finally {
    isSending.value = false
  }
}

async function sendSuggestion(text) { appendUserText(text); await sendPayload({ text }) }

async function sendQuickText(text) { draftMessage.value = text; await sendTextMessage() }

// 新增：快捷回复
async function sendQuickReply(text) { appendUserText(text); await sendPayload({ text }) }

async function sendTextMessage() {
  const text = draftMessage.value.trim()
  const sid = senderId.value.trim()
  if (!sid) { errorMessage.value = '请先输入 sender_id。'; return }
  if (!text) return
  draftMessage.value = ''
  appendUserText(text)
  await sendPayload({ text })
}

// Shift+Enter 换行，Enter 发送
function onComposerKeydown(e) {
  if (e.key === 'Enter' && !e.shiftKey) {
    e.preventDefault()
    sendTextMessage()
  }
}

async function sendOrder(order) {
  const sid = senderId.value.trim()
  if (!sid) { errorMessage.value = '请先输入 sender_id。'; return }
  appendUserObject('order', { ...order })
  await sendPayload({
    object: { type: 'order', id: order.order_id, title: order.title, attributes: { status: order.status, amount: order.amount, created_at: order.created_at, cover_url: order.cover_url } },
  })
}

async function sendProduct(product) {
  const sid = senderId.value.trim()
  if (!sid) { errorMessage.value = '请先输入 sender_id。'; return }
  appendUserObject('product', { ...product })
  await sendPayload({
    object: { type: 'product', id: product.product_id, title: product.title, attributes: { price: product.price, cover_url: product.cover_url, description: product.description } },
  })
}

watch(() => senderId.value.trim(), async (value, prev) => {
  if (value === prev) return
  resetConversation()
  if (!value) { orders.value = []; products.value = []; return }
  await Promise.all([fetchSidebarData(), fetchChatHistory()])
})

onMounted(async () => {
  await Promise.all([fetchSidebarData(), fetchChatHistory()])
  const container = messagesContainer.value
  if (container) container.addEventListener('scroll', onMessagesScroll)
})

onUnmounted(() => {
  const container = messagesContainer.value
  if (container) container.removeEventListener('scroll', onMessagesScroll)
  destroyAvatarSdk()
})

async function playTts(botMsg) {
  const msgId = botMsg.id
  if (!botMsg.text || ttsState.value[msgId] === 'loading') return
  if (currentAudio) { currentAudio.pause(); currentAudio = null }
  for (const key of Object.keys(ttsState.value)) { if (ttsState.value[key] === 'playing') ttsState.value[key] = 'idle' }
  ttsState.value[msgId] = 'loading'
  try {
    const response = await fetch('/api/chat/tts', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ text: botMsg.text }) })
    if (!response.ok) throw new Error('TTS 请求失败')
    const blob = await response.blob()
    const url = URL.createObjectURL(blob)
    currentAudio = new Audio(url)
    ttsState.value[msgId] = 'playing'
    currentAudio.onended = () => { ttsState.value[msgId] = 'idle'; URL.revokeObjectURL(url); currentAudio = null }
    currentAudio.onerror = () => { ttsState.value[msgId] = 'idle'; URL.revokeObjectURL(url); currentAudio = null }
    await currentAudio.play()
  } catch (error) {
    ttsState.value[msgId] = 'idle'
    console.error('TTS error:', error)
  }
}

async function copyBotText(botMsg) {
  const msgId = botMsg.id
  try {
    await navigator.clipboard.writeText(botMsg.text)
    copyState.value[msgId] = true
    setTimeout(() => { copyState.value[msgId] = false }, 1800)
  } catch (error) { console.error('Copy failed:', error) }
}
</script>

<template>
  <div class="app-shell" :data-theme="theme">
    <div class="workspace">
      <!-- ════════ 左侧：数字人面板 ════════ -->
      <aside class="avatar-panel">
        <div class="avatar-panel-header">
          <h2>数字客服</h2>
          <span class="avatar-status-chip" :class="`avatar-status-${avatarStatus}`">
            {{ { offline: '未连接', connecting: '连接中', connected: '已连接', error: '异常' }[avatarStatus] }}
          </span>
        </div>

        <div class="avatar-stage">
          <div id="xmov-avatar-sdk" class="avatar-sdk-container"></div>
          <div v-if="avatarStatus !== 'connected'" class="avatar-placeholder">
            <img v-if="avatarStatus === 'offline' || avatarStatus === 'error'" :src="customerService.avatar" alt="数字人占位" />
            <span v-if="avatarStatus === 'offline' || avatarStatus === 'error'" class="placeholder-tip">连接后由此处显示 3D 数字人</span>
            <template v-if="avatarStatus === 'connecting'">
              <span class="avatar-connect-spinner"></span>
              <span class="placeholder-tip">正在加载数字人资源… {{ avatarDownloadProgress }}%</span>
              <div class="avatar-progress-track"><div class="avatar-progress-bar" :style="{ width: avatarDownloadProgress + '%' }"></div></div>
            </template>
          </div>
          <div v-if="avatarSpeaking" class="avatar-voice-indicator">
            <span class="tts-bars"><span></span><span></span><span></span></span>
            <span>正在播报</span>
          </div>
        </div>

        <p v-if="avatarSpeaking && avatarCurrentText" class="avatar-subtitle">{{ avatarCurrentText }}</p>

        <div v-if="avatarStatus === 'offline' || avatarStatus === 'error'" class="avatar-connect-form">
          <label class="avatar-field">
            <span>App ID</span>
            <input v-model="avatarAppId" type="text" placeholder="魔珐星云驱动应用 App ID" autocomplete="off" />
          </label>
          <label class="avatar-field">
            <span>App Secret</span>
            <input v-model="avatarAppSecret" type="password" placeholder="魔珐星云驱动应用 App Secret" autocomplete="off" />
          </label>
          <button type="button" class="avatar-connect-button" @click="connectAvatar">连接数字人</button>
        </div>
        <button v-else-if="avatarStatus === 'connected'" type="button" class="avatar-disconnect-button" @click="disconnectAvatar">断开数字人</button>

        <p v-if="avatarError" class="avatar-error">{{ avatarError }}</p>
        <p class="avatar-hint">连接成功后，客服的文字回复将由数字人同步语音播报。</p>
      </aside>

      <!-- ════════ 中间：聊天区 ════════ -->
      <div class="chat-card">
        <header class="chat-header">
          <div class="header-left">
            <div class="service-info">
              <div class="service-avatar-wrapper">
                <img :src="customerService.avatar" class="service-avatar" />
                <span class="status-indicator"></span>
              </div>
              <div class="service-details">
                <span class="service-name">{{ customerService.name }}</span>
                <span class="service-status">{{ customerService.status }}</span>
              </div>
            </div>
            <div class="header-stats">
              <span class="stat-item">消息 {{ conversationStats.total }}</span>
              <span class="stat-divider">|</span>
              <span class="stat-item">用户 {{ conversationStats.userCount }}</span>
              <span class="stat-divider">|</span>
              <span class="stat-item">客服 {{ conversationStats.botCount }}</span>
            </div>
          </div>
          <div class="header-actions">
            <button type="button" class="icon-button" title="导出对话" @click="exportConversation">
              <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M21 15v4a2 2 0 01-2 2H5a2 2 0 01-2-2v-4M7 10l5 5 5-5M12 15V3"/></svg>
            </button>
            <button type="button" class="icon-button" :title="theme === 'light' ? '切换深色' : '切换浅色'" @click="toggleTheme">
              <svg v-if="theme === 'light'" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M21 12.79A9 9 0 1111.21 3 7 7 0 0021 12.79z"/></svg>
              <svg v-else width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="5"/><path d="M12 1v2M12 21v2M4.22 4.22l1.42 1.42M18.36 18.36l1.42 1.42M1 12h2M21 12h2M4.22 19.78l1.42-1.42M18.36 5.64l1.42-1.42"/></svg>
            </button>
            <button type="button" class="icon-button" title="清空对话" @click="resetConversation">
              <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M3 6h18M19 6v14a2 2 0 01-2 2H7a2 2 0 01-2-2V6m3 0V4a2 2 0 012-2h4a2 2 0 012 2v2"/></svg>
            </button>
          </div>
        </header>

        <section class="controls">
          <label class="field">
            <span class="field-label">用户 ID</span>
            <div class="field-row">
              <input v-model="senderId" type="text" placeholder="u1001" />
              <button type="button" class="btn-secondary" :disabled="isLoadingSidebar" @click="fetchSidebarData">
                {{ isLoadingSidebar ? '加载中...' : '刷新' }}
              </button>
            </div>
          </label>
        </section>

        <section ref="messagesContainer" class="messages" @scroll="onMessagesScroll">
          <!-- 欢迎页 -->
          <div v-if="turns.length === 0" class="welcome">
            <div class="welcome-card">
              <div class="welcome-avatar-wrapper">
                <img :src="customerService.avatar" class="welcome-avatar" alt="小宝" />
                <span class="welcome-status-pulse"></span>
              </div>
              <h2 class="welcome-greeting">Hi，我是 {{ customerService.name }}</h2>
              <p class="welcome-subtitle">你的专属电商客服，随时为你服务</p>
              <div class="welcome-chips">
                <button v-for="chip in ['我要退款', '查订单状态', '商品推荐', '查物流']" :key="chip" type="button" class="welcome-chip" :disabled="isSending" @click="sendQuickText(chip)">{{ chip }}</button>
              </div>
            </div>
          </div>

          <!-- Turn 结构展示 -->
          <template v-for="(item, index) in turns" :key="item.id || index">
            <div v-if="item.type === 'divider'" class="history-divider"><span>{{ item.text }}</span></div>

            <div v-else class="turn-card">
              <div class="turn-header">
                <span class="turn-badge">Turn {{ item.index }}</span>
                <span class="turn-time" v-if="item.userMessage?.timestamp">{{ formatTime(item.userMessage.timestamp) }}</span>
              </div>

              <!-- 用户消息 -->
              <div v-if="item.userMessage" class="turn-section user-section">
                <div class="section-header">
                  <div class="avatar-wrapper user-avatar"><img :src="userProfile.avatar" class="avatar" /></div>
                  <div class="agent-info"><span class="agent-name">{{ userProfile.name }}</span><span class="agent-label">用户</span></div>
                </div>
                <div class="turn-bubble user-bubble">
                  <template v-if="item.userMessage.type === 'object'">
                    <div class="object-card" :class="`object-card-${item.userMessage.objectType}`">
                      <div class="object-card-badge">{{ item.userMessage.objectType === 'order' ? '订单' : '商品' }}</div>
                      <img v-if="item.userMessage.payload.cover_url" :src="item.userMessage.payload.cover_url" :alt="getObjectTitle(item.userMessage)" class="object-card-image" @error="$event.target.style.display='none'" />
                      <div class="object-card-title">{{ getObjectTitle(item.userMessage) }}</div>
                      <div class="object-card-meta">{{ getObjectIdentifier(item.userMessage) }}</div>
                      <div class="object-card-meta">
                        <span v-if="item.userMessage.objectType === 'order' && item.userMessage.payload.status" class="status-badge" :class="getStatusClass(item.userMessage.payload.status)">{{ item.userMessage.payload.status }}</span>
                        <span v-else>{{ getObjectSummary(item.userMessage) }}</span>
                      </div>
                      <div class="object-card-price">{{ getObjectAmount(item.userMessage) }}</div>
                    </div>
                  </template>
                  <template v-else><p>{{ item.userMessage.text }}</p></template>
                </div>
              </div>

              <!-- 客服回复 -->
              <div v-if="item.botMessages.length > 0" class="turn-section bot-section">
                <div class="section-header">
                  <div class="avatar-wrapper service-avatar"><img :src="customerService.avatar" class="avatar" /><span class="status-dot"></span></div>
                  <div class="agent-info"><span class="agent-name">{{ customerService.name }}</span><span class="agent-label">{{ customerService.title }}</span></div>
                </div>
                <div class="bot-messages">
                  <div v-for="(botMsg, msgIndex) in item.botMessages" :key="msgIndex" class="turn-bubble bot-bubble">
                    <template v-if="botMsg.type === 'object'">
                      <div class="object-card" :class="`object-card-${botMsg.objectType}`">
                        <div class="object-card-badge">{{ botMsg.objectType === 'order' ? '订单' : '商品' }}</div>
                        <img v-if="botMsg.payload.cover_url" :src="botMsg.payload.cover_url" :alt="getObjectTitle(botMsg)" class="object-card-image" @error="$event.target.style.display='none'" />
                        <div class="object-card-title">{{ getObjectTitle(botMsg) }}</div>
                        <div class="object-card-meta">{{ getObjectIdentifier(botMsg) }}</div>
                        <div class="object-card-meta">
                          <span v-if="botMsg.objectType === 'order' && botMsg.payload.status" class="status-badge" :class="getStatusClass(botMsg.payload.status)">{{ botMsg.payload.status }}</span>
                          <span v-else>{{ getObjectSummary(botMsg) }}</span>
                        </div>
                        <div class="object-card-price">{{ getObjectAmount(botMsg) }}</div>
                      </div>
                    </template>
                    <template v-else>
                      <div class="bot-text-row">
                        <p>{{ botMsg.text }}</p>
                        <div class="bot-actions">
                          <button type="button" class="icon-btn-small" :class="{ 'tts-playing': ttsState[botMsg.id] === 'playing' }" :disabled="ttsState[botMsg.id] === 'loading'" :title="ttsState[botMsg.id] === 'playing' ? '播放中...' : '语音播报'" @click.stop="playTts(botMsg)">
                            <span v-if="ttsState[botMsg.id] === 'loading'" class="tts-spinner"></span>
                            <span v-else-if="ttsState[botMsg.id] === 'playing'" class="tts-bars"><span></span><span></span><span></span></span>
                            <svg v-else width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polygon points="11 5 6 9 2 9 2 15 6 15 11 19 11 5"/><path d="M19.07 4.93a10 10 0 010 14.14M15.54 8.46a5 5 0 010 7.07"/></svg>
                          </button>
                          <button type="button" class="icon-btn-small" :class="{ 'copy-done': copyState[botMsg.id] }" :title="copyState[botMsg.id] ? '已复制' : '复制'" @click.stop="copyBotText(botMsg)">
                            <svg v-if="copyState[botMsg.id]" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="20 6 9 17 4 12"/></svg>
                            <svg v-else width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="9" y="9" width="13" height="13" rx="2"/><path d="M5 15H4a2 2 0 01-2-2V4a2 2 0 012-2h9a2 2 0 012 2v1"/></svg>
                          </button>
                        </div>
                      </div>
                      <span class="msg-timestamp" v-if="botMsg.timestamp">{{ formatTime(botMsg.timestamp) }}</span>
                    </template>
                    <div v-if="botMsg.suggestions && botMsg.suggestions.length > 0" class="suggestion-chips">
                      <button v-for="sug in botMsg.suggestions" :key="sug" type="button" class="suggestion-chip" :disabled="isSending" @click.stop="sendSuggestion(sug)">{{ sug }}</button>
                    </div>
                  </div>
                </div>
              </div>
            </div>
          </template>

          <!-- 回到底部按钮 -->
          <transition name="fade">
            <button v-if="showScrollBottom" type="button" class="scroll-bottom-btn" @click="scrollToBottomSmooth">
              <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="6 9 12 15 18 9"/></svg>
            </button>
          </transition>
        </section>

        <div v-if="isSending" class="typing-indicator">
          <div class="typing-avatar"><img :src="customerService.avatar" class="avatar-small" alt="小宝" /></div>
          <div class="typing-bubble">
            <span class="typing-dots"><span></span><span></span><span></span></span>
            <span class="typing-label">{{ customerService.name }}正在输入...</span>
          </div>
        </div>

        <p v-if="errorMessage" class="error-message">{{ errorMessage }}</p>

        <!-- 快捷回复条 -->
        <div v-if="showQuickReplies" class="quick-replies-bar">
          <button v-for="reply in quickReplies" :key="reply.label" type="button" class="quick-reply-chip" :disabled="isSending" @click="sendQuickReply(reply.text)">{{ reply.label }}</button>
          <button type="button" class="quick-reply-toggle" @click="showQuickReplies = !showQuickReplies">
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="6 9 12 15 18 9"/></svg>
          </button>
        </div>
        <div v-else class="quick-replies-collapsed">
          <button type="button" class="quick-reply-toggle" @click="showQuickReplies = !showQuickReplies">
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="18 15 12 9 6 15"/></svg>
            快捷回复
          </button>
        </div>

        <!-- 输入框 -->
        <form class="composer" @submit.prevent="sendTextMessage">
          <textarea
            v-model="draftMessage"
            placeholder="请输入咨询内容... (Enter 发送, Shift+Enter 换行)"
            :disabled="isSending"
            rows="1"
            @keydown="onComposerKeydown"
          ></textarea>
          <div class="composer-right">
            <span class="char-counter" :class="{ 'char-warn': charCount > maxChars * 0.8 }">{{ charCount }}/{{ maxChars }}</span>
            <button type="submit" :disabled="isSending || !draftMessage.trim()">{{ isSending ? '发送中...' : '发送' }}</button>
          </div>
        </form>
      </div>

      <!-- ════════ 右侧：业务对象面板 ════════ -->
      <aside class="sidebar">
        <div class="sidebar-header"><h2>业务对象</h2></div>

        <div class="tabs">
          <button type="button" class="tab-button" :class="{ active: activeTab === 'orders' }" @click="activeTab = 'orders'">订单</button>
          <button type="button" class="tab-button" :class="{ active: activeTab === 'products' }" @click="activeTab = 'products'">商品</button>
        </div>

        <!-- 订单状态筛选 -->
        <div v-if="activeTab === 'orders'" class="filter-bar">
          <select v-model="orderStatusFilter" class="filter-select">
            <option v-for="opt in orderStatusOptions" :key="opt.value" :value="opt.value">{{ opt.label }}</option>
          </select>
          <span class="filter-count">{{ filteredOrders.length }} 条</span>
        </div>

        <p v-if="sidebarError" class="sidebar-error">{{ sidebarError }}</p>

        <div v-if="activeTab === 'orders'" class="sidebar-list">
          <div v-if="!filteredOrders.length && !isLoadingSidebar" class="sidebar-empty">暂无订单数据</div>
          <article v-for="order in filteredOrders" :key="order.order_id" class="sidebar-card">
            <div class="card-image-wrapper">
              <img v-if="order.cover_url" :src="order.cover_url" :alt="order.title" class="card-image" @error="$event.target.style.display='none'" />
              <div v-else class="card-image-placeholder">📦</div>
            </div>
            <div class="card-top"><div class="card-title">{{ order.title }}</div><div class="card-amount">{{ formatAmount(order.amount) }}</div></div>
            <div class="card-meta">订单号：{{ order.order_id }}</div>
            <div class="card-meta"><span class="status-badge" :class="getStatusClass(order.status)">{{ order.status }}</span></div>
            <button type="button" class="btn-secondary full-width" :disabled="isSending" @click="sendOrder(order)">发送订单</button>
          </article>
        </div>

        <div v-else class="sidebar-list">
          <div v-if="!products.length && !isLoadingSidebar" class="sidebar-empty">暂无商品数据</div>
          <article v-for="product in products" :key="product.product_id" class="sidebar-card">
            <div class="card-image-wrapper">
              <img v-if="product.cover_url" :src="product.cover_url" :alt="product.title" class="card-image" @error="$event.target.style.display='none'" />
              <div v-else class="card-image-placeholder">🛍️</div>
            </div>
            <div class="card-top"><div class="card-title">{{ product.title }}</div><div class="card-amount">{{ formatAmount(product.price) }}</div></div>
            <div class="card-meta">商品号：{{ product.product_id }}</div>
            <div class="card-meta">最近浏览 / 购买商品</div>
            <button type="button" class="btn-secondary full-width" :disabled="isSending" @click="sendProduct(product)">发送商品</button>
          </article>
        </div>
      </aside>
    </div>
  </div>
</template>

<style scoped>
/* ═══════════════════════════════════════════════════
   商务简约主题 — 浅色（默认）
   ═══════════════════════════════════════════════════ */
:global(:root) {
  --biz-bg: #f1f5f9;
  --biz-surface: #ffffff;
  --biz-surface-alt: #f8fafc;
  --biz-surface-hover: #f1f5f9;
  --biz-border: #e2e8f0;
  --biz-border-light: #f1f5f9;
  --biz-border-strong: #cbd5e1;
  --biz-text: #1e293b;
  --biz-text-secondary: #64748b;
  --biz-text-muted: #94a3b8;
  --biz-primary: #2563eb;
  --biz-primary-hover: #1d4ed8;
  --biz-primary-soft: #dbeafe;
  --biz-primary-soft-bg: #eff6ff;
  --biz-success: #16a34a;
  --biz-success-soft: #dcfce7;
  --biz-warning: #f59e0b;
  --biz-warning-soft: #fef3c7;
  --biz-info: #0284c7;
  --biz-info-soft: #e0f2fe;
  --biz-danger: #dc2626;
  --biz-danger-soft: #fee2e2;
  --biz-shadow: 0 1px 3px rgba(0,0,0,0.06), 0 1px 2px rgba(0,0,0,0.04);
  --biz-shadow-md: 0 4px 6px -1px rgba(0,0,0,0.07), 0 2px 4px -1px rgba(0,0,0,0.04);
  --biz-shadow-lg: 0 10px 15px -3px rgba(0,0,0,0.08), 0 4px 6px -2px rgba(0,0,0,0.04);
  --biz-radius-sm: 6px;
  --biz-radius-md: 10px;
  --biz-radius-lg: 14px;
}

/* 深色主题覆盖 */
:global([data-theme="dark"]) {
  --biz-bg: #0f172a;
  --biz-surface: #1e293b;
  --biz-surface-alt: #334155;
  --biz-surface-hover: #334155;
  --biz-border: #334155;
  --biz-border-light: #1e293b;
  --biz-border-strong: #475569;
  --biz-text: #e2e8f0;
  --biz-text-secondary: #94a3b8;
  --biz-text-muted: #64748b;
  --biz-primary: #3b82f6;
  --biz-primary-hover: #60a5fa;
  --biz-primary-soft: rgba(59,130,246,0.15);
  --biz-primary-soft-bg: rgba(59,130,246,0.08);
  --biz-success: #4ade80;
  --biz-success-soft: rgba(74,222,128,0.15);
  --biz-warning: #fbbf24;
  --biz-warning-soft: rgba(251,191,36,0.15);
  --biz-info: #38bdf8;
  --biz-info-soft: rgba(56,189,248,0.15);
  --biz-danger: #f87171;
  --biz-danger-soft: rgba(248,113,113,0.15);
  --biz-shadow: 0 1px 3px rgba(0,0,0,0.3);
  --biz-shadow-md: 0 4px 6px rgba(0,0,0,0.3);
  --biz-shadow-lg: 0 10px 15px rgba(0,0,0,0.4);
}

:global(*) { box-sizing: border-box; }
:global(body) {
  margin: 0;
  font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", "PingFang SC", "Microsoft YaHei", sans-serif;
  background: var(--biz-bg);
  color: var(--biz-text);
  -webkit-font-smoothing: antialiased;
}
:global(button), :global(input), :global(textarea), :global(select) { font: inherit; }
:global(#app) { min-height: 100vh; }

/* ═══ Layout ═══ */
.app-shell { min-height: 100vh; padding: 16px; position: relative; }
.workspace {
  width: min(1700px, 100%);
  margin: 0 auto;
  display: grid;
  grid-template-columns: 300px minmax(0, 1fr) 340px;
  gap: 16px;
}

/* ═══ Panels ═══ */
.avatar-panel, .chat-card, .sidebar {
  min-height: calc(100vh - 32px);
  height: calc(100vh - 32px);
  background: var(--biz-surface);
  border: 1px solid var(--biz-border);
  border-radius: var(--biz-radius-lg);
  overflow: hidden;
  box-shadow: var(--biz-shadow);
}
.chat-card { display: flex; flex-direction: column; }
.sidebar { display: flex; flex-direction: column; }

@media (max-width: 1400px) { .workspace { grid-template-columns: 260px minmax(0, 1fr) 300px; } }
@media (max-width: 1180px) {
  .workspace { grid-template-columns: 1fr; }
  .avatar-panel, .sidebar { min-height: auto; height: auto; }
  .avatar-panel .avatar-stage { min-height: 380px; }
}

/* ═══ 数字人面板 ═══ */
.avatar-panel { display: flex; flex-direction: column; }
.avatar-panel-header {
  padding: 18px 18px 12px;
  border-bottom: 1px solid var(--biz-border);
  display: flex; align-items: center; justify-content: space-between;
}
.avatar-panel-header h2 { margin: 0; font-size: 17px; font-weight: 600; color: var(--biz-text); }
.avatar-status-chip { padding: 3px 10px; border-radius: 9999px; font-size: 11px; font-weight: 600; }
.avatar-status-offline { background: var(--biz-surface-alt); color: var(--biz-text-muted); border: 1px solid var(--biz-border); }
.avatar-status-connecting { background: var(--biz-warning-soft); color: var(--biz-warning); border: 1px solid var(--biz-warning); }
.avatar-status-connected { background: var(--biz-success-soft); color: var(--biz-success); border: 1px solid var(--biz-success); }
.avatar-status-error { background: var(--biz-danger-soft); color: var(--biz-danger); border: 1px solid var(--biz-danger); }

.avatar-stage {
  position: relative; flex: 1; min-height: 280px; margin: 12px;
  border-radius: var(--biz-radius-md); overflow: hidden;
  background: var(--biz-surface-alt); border: 1px solid var(--biz-border);
}
.avatar-sdk-container { width: 100%; height: 100%; }
.avatar-placeholder { position: absolute; inset: 0; display: flex; flex-direction: column; align-items: center; justify-content: center; gap: 12px; pointer-events: none; }
.avatar-placeholder img { width: 80px; height: 80px; border-radius: 50%; border: 2px solid var(--biz-border); }
.placeholder-tip { font-size: 12px; color: var(--biz-text-muted); text-align: center; padding: 0 16px; }
.avatar-connect-spinner { width: 36px; height: 36px; border: 3px solid var(--biz-border); border-top-color: var(--biz-primary); border-radius: 50%; animation: spin 0.8s linear infinite; }
.avatar-progress-track { width: 70%; height: 5px; border-radius: 9999px; background: var(--biz-border); overflow: hidden; }
.avatar-progress-bar { height: 100%; background: var(--biz-primary); border-radius: 9999px; transition: width 0.25s; }

.avatar-voice-indicator { position: absolute; top: 8px; right: 8px; display: inline-flex; align-items: center; gap: 6px; padding: 4px 10px; border-radius: 9999px; background: var(--biz-surface); border: 1px solid var(--biz-primary); color: var(--biz-primary); font-size: 11px; font-weight: 600; }
.avatar-subtitle { margin: 8px 12px 0; padding: 8px 12px; max-height: 80px; overflow-y: auto; font-size: 12px; line-height: 1.5; color: var(--biz-text-secondary); background: var(--biz-surface-alt); border: 1px solid var(--biz-border); border-radius: var(--biz-radius-sm); }
.avatar-connect-form { display: flex; flex-direction: column; gap: 10px; padding: 14px; }
.avatar-field { display: flex; flex-direction: column; gap: 4px; }
.avatar-field span { color: var(--biz-text-secondary); font-size: 12px; font-weight: 500; }
.avatar-field input { width: 100%; min-width: 0; padding: 8px 10px; border: 1px solid var(--biz-border-strong); border-radius: var(--biz-radius-md); background: var(--biz-surface); color: var(--biz-text); font-size: 13px; }
.avatar-field input:focus { outline: none; border-color: var(--biz-primary); box-shadow: 0 0 0 3px var(--biz-primary-soft); }
.avatar-connect-button { min-height: 40px; padding: 8px 14px; border: none; border-radius: var(--biz-radius-md); background: var(--biz-primary); color: #fff; font-size: 14px; font-weight: 600; cursor: pointer; transition: background 0.15s; }
.avatar-connect-button:hover { background: var(--biz-primary-hover); }
.avatar-disconnect-button { margin: 12px; min-height: 38px; padding: 8px 14px; border: 1px solid var(--biz-border); border-radius: var(--biz-radius-md); background: var(--biz-surface); color: var(--biz-text-secondary); font-size: 13px; font-weight: 600; cursor: pointer; }
.avatar-disconnect-button:hover { background: var(--biz-danger-soft); border-color: var(--biz-danger); color: var(--biz-danger); }
.avatar-error { margin: 0 12px; color: var(--biz-danger); font-size: 12px; font-weight: 500; }
.avatar-hint { margin: auto 12px 12px; padding-top: 8px; border-top: 1px solid var(--biz-border); color: var(--biz-text-muted); font-size: 11px; line-height: 1.5; }

/* ═══ Chat Header ═══ */
.chat-header { padding: 14px 20px; border-bottom: 1px solid var(--biz-border); display: flex; justify-content: space-between; align-items: center; gap: 12px; }
.header-left { display: flex; align-items: center; gap: 16px; flex: 1; }
.service-info { display: flex; align-items: center; gap: 10px; }
.service-avatar-wrapper { position: relative; flex-shrink: 0; }
.service-avatar { width: 40px; height: 40px; border-radius: 50%; object-fit: cover; border: 2px solid var(--biz-border); }
.status-indicator { position: absolute; bottom: 0; right: 0; width: 10px; height: 10px; background: var(--biz-success); border: 2px solid var(--biz-surface); border-radius: 50%; }
.service-details { display: flex; flex-direction: column; gap: 1px; }
.service-name { font-size: 14px; font-weight: 600; color: var(--biz-text); }
.service-status { font-size: 11px; color: var(--biz-success); font-weight: 500; }
.header-stats { display: flex; align-items: center; gap: 6px; font-size: 12px; color: var(--biz-text-muted); }
.stat-divider { color: var(--biz-border-strong); }
.header-actions { display: flex; gap: 4px; }
.icon-button { width: 34px; height: 34px; border: 1px solid var(--biz-border); border-radius: var(--biz-radius-md); background: var(--biz-surface); color: var(--biz-text-secondary); cursor: pointer; display: inline-flex; align-items: center; justify-content: center; transition: all 0.15s; }
.icon-button:hover { background: var(--biz-surface-hover); border-color: var(--biz-primary); color: var(--biz-primary); }

/* ═══ Controls ═══ */
.controls { padding: 12px 20px; border-bottom: 1px solid var(--biz-border); }
.field { display: flex; flex-direction: column; gap: 4px; }
.field-label { color: var(--biz-text-secondary); font-size: 12px; font-weight: 500; }
.field-row { display: flex; gap: 8px; }
.field input { width: 100%; min-width: 0; padding: 8px 12px; border: 1px solid var(--biz-border-strong); border-radius: var(--biz-radius-md); background: var(--biz-surface); color: var(--biz-text); font-size: 14px; }
.field input:focus { outline: none; border-color: var(--biz-primary); box-shadow: 0 0 0 3px var(--biz-primary-soft); }

/* ═══ Messages ═══ */
.messages { flex: 1; min-height: 0; overflow-y: auto; scrollbar-gutter: stable; padding: 16px; display: flex; flex-direction: column; gap: 12px; }

.turn-card { flex-shrink: 0; display: flex; flex-direction: column; gap: 10px; padding: 14px 16px; background: var(--biz-surface); border: 1px solid var(--biz-border); border-radius: var(--biz-radius-md); transition: box-shadow 0.2s; animation: msgEnter 0.3s ease-out both; }
@keyframes msgEnter { from { opacity: 0; transform: translateY(12px); } to { opacity: 1; transform: translateY(0); } }
.turn-card:hover { box-shadow: var(--biz-shadow-md); }
.turn-header { display: flex; align-items: center; gap: 8px; padding-bottom: 8px; border-bottom: 1px solid var(--biz-border-light); }
.turn-badge { padding: 2px 8px; background: var(--biz-primary); color: #fff; font-size: 11px; font-weight: 600; border-radius: 4px; }
.turn-time { font-size: 11px; color: var(--biz-text-muted); }

.turn-section { display: flex; flex-direction: column; gap: 6px; }
.section-header { display: flex; align-items: center; gap: 8px; }
.avatar-wrapper { position: relative; flex-shrink: 0; }
.avatar { width: 32px; height: 32px; border-radius: 50%; object-fit: cover; border: 2px solid var(--biz-border); background: var(--biz-surface-alt); }
.user-avatar .avatar { border-color: var(--biz-primary); }
.service-avatar .avatar { border-color: var(--biz-success); }
.status-dot { position: absolute; bottom: 0; right: 0; width: 8px; height: 8px; background: var(--biz-success); border: 1px solid var(--biz-surface); border-radius: 50%; }
.agent-info { display: flex; flex-direction: column; gap: 1px; }
.agent-name { font-size: 13px; font-weight: 600; color: var(--biz-text); }
.agent-label { font-size: 11px; color: var(--biz-text-muted); }
.user-section .agent-name { color: var(--biz-primary); }
.bot-section .agent-name { color: var(--biz-success); }

.turn-bubble { padding: 10px 14px; border-radius: var(--biz-radius-md); max-width: 100%; }
.user-bubble { background: var(--biz-primary); color: #fff; margin-left: auto; max-width: 85%; }
.bot-bubble { background: var(--biz-surface-alt); border: 1px solid var(--biz-border); }
.bot-messages { display: flex; flex-direction: column; gap: 6px; }
.turn-bubble p { margin: 0; font-size: 14px; line-height: 1.6; white-space: pre-wrap; word-break: break-word; }
.user-bubble p { color: #fff; }
.msg-timestamp { font-size: 10px; color: var(--biz-text-muted); margin-top: 4px; display: block; }

/* 历史分隔线 */
.history-divider { flex-shrink: 0; display: flex; align-items: center; gap: 10px; color: var(--biz-text-muted); font-size: 12px; padding: 4px 0; }
.history-divider::before, .history-divider::after { content: ""; flex: 1; height: 1px; background: var(--biz-border); }
.history-divider span { padding: 4px 10px; border-radius: 9999px; background: var(--biz-surface); border: 1px solid var(--biz-border); }

/* 欢迎页 */
.welcome { flex: 1; display: flex; align-items: center; justify-content: center; padding: 16px; }
.welcome-card { max-width: 400px; width: 100%; padding: 32px 28px; background: var(--biz-surface); border: 1px solid var(--biz-border); border-radius: var(--biz-radius-lg); text-align: center; box-shadow: var(--biz-shadow-md); }
.welcome-avatar-wrapper { position: relative; display: inline-block; margin-bottom: 16px; }
.welcome-avatar { width: 72px; height: 72px; border-radius: 50%; border: 3px solid var(--biz-primary); }
.welcome-status-pulse { position: absolute; bottom: 4px; right: 4px; width: 14px; height: 14px; background: var(--biz-success); border: 2px solid var(--biz-surface); border-radius: 50%; }
.welcome-greeting { margin: 0 0 6px; font-size: 22px; font-weight: 700; color: var(--biz-text); }
.welcome-subtitle { margin: 0 0 20px; color: var(--biz-text-secondary); font-size: 14px; }
.welcome-chips { display: flex; flex-wrap: wrap; gap: 8px; justify-content: center; }
.welcome-chip { padding: 8px 16px; border: 1px solid var(--biz-border); border-radius: 9999px; background: var(--biz-surface); color: var(--biz-primary); font-size: 13px; font-weight: 500; cursor: pointer; transition: all 0.15s; }
.welcome-chip:hover:not(:disabled) { background: var(--biz-primary-soft-bg); border-color: var(--biz-primary); }
.welcome-chip:disabled { opacity: 0.4; cursor: not-allowed; }

/* 回到底部 */
.scroll-bottom-btn { position: sticky; bottom: 10px; left: 100%; width: 36px; height: 36px; border: 1px solid var(--biz-border); border-radius: 50%; background: var(--biz-surface); color: var(--biz-text-secondary); cursor: pointer; display: flex; align-items: center; justify-content: center; box-shadow: var(--biz-shadow-md); transition: all 0.15s; z-index: 10; }
.scroll-bottom-btn:hover { background: var(--biz-primary); color: #fff; border-color: var(--biz-primary); }
.fade-enter-active, .fade-leave-active { transition: opacity 0.2s; }
.fade-enter-from, .fade-leave-to { opacity: 0; }

/* Typing indicator */
.typing-indicator { flex-shrink: 0; display: flex; align-items: flex-end; gap: 8px; padding: 0 16px; }
.avatar-small { width: 28px; height: 28px; border-radius: 50%; border: 2px solid var(--biz-success); }
.typing-bubble { display: flex; align-items: center; gap: 6px; padding: 8px 14px; background: var(--biz-surface-alt); border: 1px solid var(--biz-border); border-radius: var(--biz-radius-md); }
.typing-dots { display: flex; gap: 3px; }
.typing-dots span { width: 6px; height: 6px; border-radius: 50%; background: var(--biz-text-muted); animation: dotBounce 1.2s infinite; }
.typing-dots span:nth-child(1) { animation-delay: 0s; }
.typing-dots span:nth-child(2) { animation-delay: 0.2s; }
.typing-dots span:nth-child(3) { animation-delay: 0.4s; }
@keyframes dotBounce { 0%,60%,100% { transform: translateY(0); opacity: 0.3; } 30% { transform: translateY(-6px); opacity: 1; } }
.typing-label { font-size: 12px; color: var(--biz-text-muted); }

/* ═══ 快捷回复条 ═══ */
.quick-replies-bar { display: flex; gap: 6px; padding: 8px 20px; border-top: 1px solid var(--biz-border); background: var(--biz-surface-alt); overflow-x: auto; }
.quick-reply-chip { white-space: nowrap; padding: 5px 12px; border: 1px solid var(--biz-border); border-radius: 9999px; background: var(--biz-surface); color: var(--biz-primary); font-size: 12px; font-weight: 500; cursor: pointer; transition: all 0.15s; }
.quick-reply-chip:hover:not(:disabled) { background: var(--biz-primary-soft-bg); border-color: var(--biz-primary); }
.quick-reply-chip:disabled { opacity: 0.4; cursor: not-allowed; }
.quick-reply-toggle { white-space: nowrap; padding: 5px 10px; border: 1px solid var(--biz-border); border-radius: 9999px; background: var(--biz-surface); color: var(--biz-text-muted); font-size: 12px; cursor: pointer; display: inline-flex; align-items: center; gap: 4px; }
.quick-replies-collapsed { padding: 6px 20px; border-top: 1px solid var(--biz-border); background: var(--biz-surface-alt); }

/* ═══ Composer ═══ */
.composer { flex-shrink: 0; display: flex; align-items: flex-end; gap: 10px; padding: 12px 20px; border-top: 1px solid var(--biz-border); background: var(--biz-surface); }
.composer textarea { flex: 1; min-width: 0; min-height: 40px; max-height: 120px; padding: 10px 14px; border: 1px solid var(--biz-border-strong); border-radius: var(--biz-radius-md); background: var(--biz-surface); color: var(--biz-text); font-size: 14px; line-height: 1.5; resize: none; }
.composer textarea:focus { outline: none; border-color: var(--biz-primary); box-shadow: 0 0 0 3px var(--biz-primary-soft); }
.composer-right { display: flex; flex-direction: column; align-items: flex-end; gap: 4px; }
.char-counter { font-size: 10px; color: var(--biz-text-muted); }
.char-counter.char-warn { color: var(--biz-warning); }
.composer button { min-width: 80px; padding: 10px 18px; border: none; border-radius: var(--biz-radius-md); background: var(--biz-primary); color: #fff; font-size: 14px; font-weight: 600; cursor: pointer; transition: background 0.15s; }
.composer button:hover:not(:disabled) { background: var(--biz-primary-hover); }
.composer button:disabled { opacity: 0.5; cursor: not-allowed; }

/* ═══ Sidebar ═══ */
.sidebar-header { padding: 14px 20px; border-bottom: 1px solid var(--biz-border); }
.sidebar-header h2 { margin: 0; font-size: 18px; font-weight: 600; color: var(--biz-text); }
.tabs { display: flex; gap: 6px; padding: 10px 20px; border-bottom: 1px solid var(--biz-border); }
.tab-button { min-width: 70px; padding: 7px 14px; border: 1px solid var(--biz-border); border-radius: var(--biz-radius-md); background: var(--biz-surface); color: var(--biz-text-secondary); font-size: 13px; font-weight: 600; cursor: pointer; transition: all 0.15s; }
.tab-button:hover:not(:disabled) { background: var(--biz-surface-hover); }
.tab-button.active { background: var(--biz-primary); border-color: var(--biz-primary); color: #fff; }

.filter-bar { display: flex; align-items: center; gap: 8px; padding: 8px 20px; border-bottom: 1px solid var(--biz-border); }
.filter-select { flex: 1; min-width: 0; padding: 6px 10px; border: 1px solid var(--biz-border-strong); border-radius: var(--biz-radius-sm); background: var(--biz-surface); color: var(--biz-text); font-size: 13px; }
.filter-count { font-size: 12px; color: var(--biz-text-muted); white-space: nowrap; }

.sidebar-list { flex: 1; min-height: 0; overflow-y: auto; padding: 12px 20px 20px; display: flex; flex-direction: column; gap: 10px; }
.sidebar-card { padding: 12px; border: 1px solid var(--biz-border); border-radius: var(--biz-radius-md); background: var(--biz-surface); display: flex; flex-direction: column; gap: 8px; transition: all 0.15s; }
.sidebar-card:hover { border-color: var(--biz-primary); box-shadow: var(--biz-shadow-md); transform: translateY(-1px); }
.card-image-wrapper { width: 100%; height: 120px; border-radius: var(--biz-radius-sm); overflow: hidden; background: var(--biz-surface-alt); border: 1px solid var(--biz-border); display: flex; align-items: center; justify-content: center; }
.card-image { width: 100%; height: 100%; object-fit: cover; transition: transform 0.2s; }
.sidebar-card:hover .card-image { transform: scale(1.05); }
.card-image-placeholder { font-size: 32px; opacity: 0.4; }
.card-top { display: flex; gap: 8px; justify-content: space-between; align-items: flex-start; }
.card-title { font-size: 14px; line-height: 1.4; color: var(--biz-text); font-weight: 600; flex: 1; }
.card-amount { flex-shrink: 0; color: var(--biz-primary); font-weight: 700; font-size: 14px; }
.card-meta { font-size: 12px; color: var(--biz-text-secondary); }
.sidebar-empty { margin: auto; color: var(--biz-text-muted); text-align: center; line-height: 1.6; }

/* ═══ 对象卡片 ═══ */
.object-card { min-width: 200px; padding: 8px; }
.object-card-badge { display: inline-block; padding: 2px 8px; border-radius: 4px; font-size: 11px; font-weight: 600; background: var(--biz-primary-soft); color: var(--biz-primary); margin-bottom: 6px; }
.user-bubble .object-card-badge { background: rgba(255,255,255,0.2); color: #fff; }
.object-card-image { width: 100%; height: 120px; object-fit: cover; border-radius: var(--biz-radius-sm); margin-bottom: 6px; border: 1px solid var(--biz-border); }
.object-card-title { font-size: 14px; font-weight: 600; color: var(--biz-text); }
.user-bubble .object-card-title { color: #fff; }
.object-card-meta { font-size: 12px; color: var(--biz-text-secondary); margin-top: 2px; }
.user-bubble .object-card-meta { color: rgba(255,255,255,0.85); }
.object-card-price { font-size: 14px; font-weight: 600; color: var(--biz-text); margin-top: 4px; }
.user-bubble .object-card-price { color: #fff; }

/* ═══ 状态徽章 ═══ */
.status-badge { display: inline-flex; align-items: center; padding: 2px 8px; border-radius: 9999px; font-size: 11px; font-weight: 600; }
.status-warning { background: var(--biz-warning-soft); color: var(--biz-warning); }
.status-info { background: var(--biz-info-soft); color: var(--biz-info); }
.status-success { background: var(--biz-success-soft); color: var(--biz-success); }
.status-muted { background: var(--biz-surface-alt); color: var(--biz-text-muted); border: 1px solid var(--biz-border); }
.status-danger { background: var(--biz-danger-soft); color: var(--biz-danger); }

/* ═══ 按钮 ═══ */
.btn-secondary { min-height: 38px; padding: 7px 14px; border: 1px solid var(--biz-border); border-radius: var(--biz-radius-md); background: var(--biz-surface); color: var(--biz-text); cursor: pointer; font-size: 13px; font-weight: 600; transition: all 0.15s; }
.btn-secondary:hover:not(:disabled) { background: var(--biz-surface-hover); border-color: var(--biz-primary); color: var(--biz-primary); }
.btn-secondary:disabled { opacity: 0.5; cursor: not-allowed; }
.full-width { width: 100%; }

/* ═══ 小图标按钮 ═══ */
.bot-text-row { display: flex; align-items: flex-start; gap: 6px; }
.bot-text-row p { flex: 1; margin: 0; }
.bot-actions { display: flex; gap: 4px; flex-shrink: 0; align-items: center; }
.icon-btn-small { flex-shrink: 0; width: 28px; height: 28px; padding: 0; border: 1px solid var(--biz-border); border-radius: 6px; background: var(--biz-surface); cursor: pointer; display: inline-flex; align-items: center; justify-content: center; transition: all 0.15s; color: var(--biz-text-muted); }
.icon-btn-small:hover:not(:disabled) { background: var(--biz-primary-soft-bg); border-color: var(--biz-primary); color: var(--biz-primary); }
.icon-btn-small:disabled { opacity: 0.5; cursor: not-allowed; }
.icon-btn-small.tts-playing { background: var(--biz-primary-soft); border-color: var(--biz-primary); color: var(--biz-primary); }
.icon-btn-small.copy-done { background: var(--biz-success-soft); border-color: var(--biz-success); color: var(--biz-success); }
.tts-bars { display: inline-flex; align-items: flex-end; gap: 2px; height: 14px; }
.tts-bars span { width: 2px; background: var(--biz-primary); border-radius: 1px; animation: barBounce 0.6s infinite; }
.tts-bars span:nth-child(1) { height: 6px; animation-delay: 0s; }
.tts-bars span:nth-child(2) { height: 12px; animation-delay: 0.15s; }
.tts-bars span:nth-child(3) { height: 8px; animation-delay: 0.3s; }
@keyframes barBounce { 0%,100% { transform: scaleY(0.5); } 50% { transform: scaleY(1); } }
.tts-spinner { width: 12px; height: 12px; border: 2px solid var(--biz-border); border-top-color: var(--biz-primary); border-radius: 50%; animation: spin 0.6s linear infinite; }
@keyframes spin { to { transform: rotate(360deg); } }

/* ═══ 建议词 ═══ */
.suggestion-chips { display: flex; flex-wrap: wrap; gap: 6px; margin-top: 8px; padding-top: 8px; border-top: 1px solid var(--biz-border-light); }
.suggestion-chip { padding: 4px 10px; border: 1px solid var(--biz-border); border-radius: 9999px; background: var(--biz-surface); color: var(--biz-primary); font-size: 12px; font-weight: 500; cursor: pointer; transition: all 0.15s; }
.suggestion-chip:hover:not(:disabled) { background: var(--biz-primary-soft-bg); border-color: var(--biz-primary); }
.suggestion-chip:disabled { opacity: 0.4; cursor: not-allowed; }

/* ═══ Error ═══ */
.error-message, .sidebar-error { margin: 0; padding: 0 20px 10px; color: var(--biz-danger); font-size: 12px; font-weight: 500; }
.sidebar-error { padding: 8px 20px; }

/* ═══ Mobile ═══ */
@media (max-width: 720px) {
  .app-shell { padding: 0; }
  .workspace { gap: 0; }
  .avatar-panel, .chat-card, .sidebar { min-height: auto; height: auto; border-radius: 0; border-left: none; border-right: none; }
  .chat-card { min-height: 100vh; }
  .header-left { flex-direction: column; align-items: flex-start; gap: 6px; }
  .field-row { flex-direction: column; }
}
</style>
