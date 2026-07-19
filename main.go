package main

import (
	"encoding/json"
	"io"
	"log"
	"net/http"
	"os"
	"regexp"
	"strings"
	"time"

	"github.com/PaulSonOfLars/gotgbot/v2"
	"github.com/PaulSonOfLars/gotgbot/v2/ext"
	"github.com/PaulSonOfLars/gotgbot/v2/ext/handlers"
	"github.com/PaulSonOfLars/gotgbot/v2/ext/handlers/filters"
	"github.com/gotd/td/telegram"
	"github.com/gotd/td/telegram/auth"
	"github.com/gotd/td/telegram/dcs"
	"github.com/gotd/td/telegram/message"
	"github.com/gotd/td/tg"
	"golang.org/x/net/proxy"
)

var (
	BOT_TOKEN   = "8895080427:AAE02i4cD0NeWVOShOC6btza4PMitpJxgk8"
	API_ID      = 39328144
	API_HASH    = "b4c02b2f6297f1b61d3073fd50629711"
	WEBHOOK_URL = "https://sessionbotnew-1.onrender.com/webhook"
)

var userSessions = make(map[int64]*telegram.Client)
var userStates = make(map[int64]string)

func main() {
	// Запускаем бота через webhook
	b, err := gotgbot.NewBot(BOT_TOKEN, nil)
	if err != nil {
		log.Fatal(err)
	}

	// Создаём вебхук
	http.HandleFunc("/webhook", func(w http.ResponseWriter, r *http.Request) {
		if r.Method != "POST" {
			w.WriteHeader(405)
			return
		}

		body, err := io.ReadAll(r.Body)
		if err != nil {
			w.WriteHeader(400)
			return
		}
		defer r.Body.Close()

		var update gotgbot.Update
		if err := json.Unmarshal(body, &update); err != nil {
			w.WriteHeader(400)
			return
		}

		handleUpdate(b, &update)
		w.WriteHeader(200)
	})

	http.HandleFunc("/", func(w http.ResponseWriter, r *http.Request) {
		w.Write([]byte("Bot is running!"))
	})

	// Устанавливаем webhook
	_, err = b.SetWebhook(&gotgbot.SetWebhookOpts{
		URL: WEBHOOK_URL,
	})
	if err != nil {
		log.Printf("Webhook error: %v", err)
	}

	port := os.Getenv("PORT")
	if port == "" {
		port = "10000"
	}
	log.Printf("Бот запущен на порту %s", port)
	log.Fatal(http.ListenAndServe(":"+port, nil))
}

func handleUpdate(b *gotgbot.Bot, update *gotgbot.Update) {
	if update.Message != nil {
		msg := update.Message
		chatId := msg.Chat.Id
		text := msg.Text
		userId := msg.From.Id

		if text == "/start" {
			keyboard := gotgbot.InlineKeyboardMarkup{
				InlineKeyboard: [][]gotgbot.InlineKeyboardButton{
					{{Text: "🔑 Войти", CallbackData: "login"}},
					{{Text: "🆕 Новый аккаунт", CallbackData: "new"}},
				},
			}
			b.SendMessage(chatId, "👋 Привет! Войди в аккаунт:", &gotgbot.SendMessageOpts{
				ReplyMarkup: keyboard,
			})
			return
		}

		if state, ok := userStates[userId]; ok && state == "awaiting_session" {
			// Пытаемся войти по сессии
			sessionStr := text
			go loginWithSession(chatId, userId, sessionStr, b)
			return
		}
	}

	if update.CallbackQuery != nil {
		query := update.CallbackQuery
		chatId := query.Message.Chat.Id
		messageId := query.Message.MessageId
		userId := query.From.Id
		data := query.Data

		// Отвечаем на callback
		b.AnswerCallbackQuery(query.Id, &gotgbot.AnswerCallbackQueryOpts{})

		if data == "login" {
			userStates[userId] = "awaiting_session"
			b.EditMessageText("🔑 Отправь session string:", &gotgbot.EditMessageTextOpts{
				ChatId:    chatId,
				MessageId: messageId,
			})
		} else if data == "new" {
			b.EditMessageText("🆕 Создай аккаунт в Telegram, потом войди через /start", &gotgbot.EditMessageTextOpts{
				ChatId:    chatId,
				MessageId: messageId,
			})
		} else if data == "logout" {
			if client, ok := userSessions[userId]; ok {
				client.Close()
				delete(userSessions, userId)
			}
			delete(userStates, userId)
			b.EditMessageText("🚪 Вышел. Используй /start для входа", &gotgbot.EditMessageTextOpts{
				ChatId:    chatId,
				MessageId: messageId,
			})
		} else {
			b.EditMessageText("⚠️ Функция в разработке", &gotgbot.EditMessageTextOpts{
				ChatId:    chatId,
				MessageId: messageId,
			})
		}
	}
}

func loginWithSession(chatId int64, userId int64, sessionStr string, b *gotgbot.Bot) {
	// Создаём клиент с сессией
	session := &tg.Session{
		Session: sessionStr,
	}

	client := telegram.NewClient(
		API_ID,
		API_HASH,
		telegram.Options{
			SessionStorage: &sessionStorage{session: session},
			DC:             dcs.DC{},
		},
	)

	err := client.Run(nil, func(ctx context.Context) error {
		// Проверяем, что вошли
		api := tg.NewClient(client)
		_, err := api.UsersGetUsers(ctx, []tg.InputUserClass{&tg.InputUserSelf{}})
		return err
	})

	if err != nil {
		b.SendMessage(chatId, "❌ Сессия невалидна: "+err.Error(), nil)
		delete(userStates, userId)
		return
	}

	userSessions[userId] = client
	delete(userStates, userId)
	b.SendMessage(chatId, "✅ Вход выполнен!", nil)

	// Показываем меню
	keyboard := gotgbot.InlineKeyboardMarkup{
		InlineKeyboard: [][]gotgbot.InlineKeyboardButton{
			{{Text: "📤 Отправить сообщение", CallbackData: "send"}},
			{{Text: "📖 Читать сообщения", CallbackData: "read"}},
			{{Text: "🚪 Выйти", CallbackData: "logout"}},
		},
	}
	b.SendMessage(chatId, "📱 Меню:", &gotgbot.SendMessageOpts{
		ReplyMarkup: keyboard,
	})
}

// Хранилище сессии
type sessionStorage struct {
	session *tg.Session
}

func (s *sessionStorage) Load(ctx context.Context) (*tg.Session, error) {
	return s.session, nil
}

func (s *sessionStorage) Save(ctx context.Context, session *tg.Session) error {
	s.session = session
	return nil
}