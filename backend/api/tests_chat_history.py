import json
import uuid
from django.test import TestCase, Client
from django.urls import reverse
from unittest.mock import patch, MagicMock
from api.models import Session, Message, SessionSummary

class ChatHistoryAPITests(TestCase):
    def setUp(self):
        self.client = Client()

    def test_create_session(self):
        """
        1. セッション作成API (POST /api/sessions/) が機能し、
        UUID IDとステータス active が正しく返却されること。
        """
        url = reverse('session_list_create')
        payload = {"certification_name": "基本情報技術者"}
        
        response = self.client.post(
            url,
            data=json.dumps(payload),
            content_type='application/json'
        )
        
        self.assertEqual(response.status_code, 201)
        data = response.json()
        
        # UUID IDとステータス active が正しく返却されること
        self.assertIn('id', data)
        self.assertEqual(data['status'], 'active')
        self.assertEqual(data['certification_name'], '基本情報技術者')
        self.assertIn('created_at', data)
        
        # 正しいUUID形式であること
        try:
            uuid.UUID(data['id'])
        except ValueError:
            self.fail("Returned session ID is not a valid UUID")

        # データベースに保存されていること
        session = Session.objects.filter(id=data['id']).first()
        self.assertIsNotNone(session)
        self.assertEqual(session.certification_name, "基本情報技術者")
        self.assertEqual(session.status, "active")

    def test_get_sessions_list(self):
        """
        2. セッション一覧API (GET /api/sessions/) が、
        作成したセッションを一覧表示すること。
        """
        # テストデータを事前に登録
        session1 = Session.objects.create(certification_name="応用情報技術者")
        session2 = Session.objects.create(certification_name="ITパスポート")
        
        url = reverse('session_list_create')
        response = self.client.get(url)
        
        self.assertEqual(response.status_code, 200)
        data = response.json()
        
        # 作成したセッションが含まれていること
        self.assertEqual(len(data), 2)
        ids = [s['id'] for s in data]
        self.assertIn(str(session1.id), ids)
        self.assertIn(str(session2.id), ids)
        
        # 最新順に並んでいるか確認（DjangoのOrderingは['-created_at']）
        self.assertEqual(data[0]['id'], str(session2.id))
        self.assertEqual(data[1]['id'], str(session1.id))

    def test_get_session_history_initial(self):
        """
        3. セッション履歴API (GET /api/sessions/<id>/history/) が、
        初期状態で空のメッセージ配列と空の要約テキストを正しく返却すること。
        """
        session = Session.objects.create(certification_name="基本情報技術者")
        
        url = reverse('session_history', kwargs={'id': session.id})
        response = self.client.get(url)
        
        self.assertEqual(response.status_code, 200)
        data = response.json()
        
        # セッション情報が正しいこと
        self.assertEqual(data['session']['id'], str(session.id))
        self.assertEqual(data['session']['certification_name'], "基本情報技術者")
        self.assertEqual(data['session']['status'], "active")
        
        # 初期状態で空の要約テキスト
        self.assertEqual(data['summary']['summary_text'], "")
        self.assertIsNone(data['summary']['updated_at'])
        
        # 初期状態で空のメッセージ配列
        self.assertEqual(data['messages'], [])

    @patch.dict('os.environ', {'GEMINI_API_KEY': 'fake_key'})
    @patch('api.views.genai.Client')
    @patch('api.views.trigger_voicevox')
    @patch('api.views.summary_executor')
    def test_post_session_message_success(self, mock_executor, mock_voicevox, mock_genai_client):
        """
        4. メッセージ対話API (POST /api/sessions/<id>/message/) が、Gemini APIをシミュレートし、
        ユーザーのメッセージおよびAIの応答（評価、進捗含む）を正しくデータベースに保存し、レスポンスを返すこと。
        """
        session = Session.objects.create(certification_name="基本情報技術者")
        url = reverse('session_message', kwargs={'id': session.id})
        payload = {"content": "オブジェクト指向について教えてください。"}
        
        # Gemini API の応答のシミュレーション
        mock_response_text = json.dumps({
            "coaching_comment": "オブジェクト指向は、データと処理を一つの『オブジェクト』としてまとめる考え方です！頑張りましょう！",
            "daily_rating": "A",
            "progress_status": "オブジェクト指向の基本概念について質問があり、学習意欲が高いです。"
        })
        
        mock_client_instance = MagicMock()
        mock_genai_client.return_value = mock_client_instance
        
        mock_response_obj = MagicMock()
        mock_response_obj.text = mock_response_text
        mock_client_instance.models.generate_content.return_value = mock_response_obj
        
        response = self.client.post(
            url,
            data=json.dumps(payload),
            content_type='application/json'
        )
        
        self.assertEqual(response.status_code, 201)
        data = response.json()
        
        # ユーザーとアシスタントのメッセージが返却されること
        self.assertIn('user_message', data)
        self.assertIn('assistant_message', data)
        
        user_msg = data['user_message']
        assistant_msg = data['assistant_message']
        
        self.assertEqual(user_msg['sender_role'], 'user')
        self.assertEqual(user_msg['content'], "オブジェクト指向について教えてください。")
        
        self.assertEqual(assistant_msg['sender_role'], 'assistant')
        self.assertEqual(assistant_msg['content'], "オブジェクト指向は、データと処理を一つの『オブジェクト』としてまとめる考え方です！頑張りましょう！")
        self.assertEqual(assistant_msg['rating'], "A")
        self.assertEqual(assistant_msg['progress_status'], "オブジェクト指向の基本概念について質問があり、学習意欲が高いです。")
        
        # データベースに正しく保存されていること
        messages = Message.objects.filter(session=session).order_by('sent_at')
        self.assertEqual(messages.count(), 2)
        
        db_user_msg = messages[0]
        self.assertEqual(db_user_msg.sender_role, 'user')
        self.assertEqual(db_user_msg.content, "オブジェクト指向について教えてください。")
        
        db_assistant_msg = messages[1]
        self.assertEqual(db_assistant_msg.sender_role, 'assistant')
        self.assertEqual(db_assistant_msg.content, "オブジェクト指向は、データと処理を一つの『オブジェクト』としてまとめる考え方です！頑張りましょう！")
        self.assertEqual(db_assistant_msg.rating, "A")
        self.assertEqual(db_assistant_msg.progress_status, "オブジェクト指向の基本概念について質問があり、学習意欲が高いです。")
        
        # VOICEVOX が呼び出されていること
        mock_voicevox.assert_called_once_with(
            "オブジェクト指向は、データと処理を一つの『オブジェクト』としてまとめる考え方です！頑張りましょう！",
            47
        )
        
        # trigger_summary=False のため、サマリー要約タスクはキューイングされないこと
        mock_executor.submit.assert_not_called()

    @patch.dict('os.environ', {'GEMINI_API_KEY': 'fake_key'})
    @patch('api.views.genai.Client')
    @patch('api.views.trigger_voicevox')
    @patch('api.views.summary_executor')
    def test_post_session_message_with_summary_trigger(self, mock_executor, mock_voicevox, mock_genai_client):
        """
        メッセージ対話APIで trigger_summary=True を渡した時に、
        セッション要約の更新タスクがバックグラウンド実行キューに入ることを検証。
        """
        session = Session.objects.create(certification_name="基本情報技術者")
        url = reverse('session_message', kwargs={'id': session.id})
        payload = {
            "content": "テストメッセージ",
            "trigger_summary": True
        }
        
        # Gemini API の応答のシミュレーション
        mock_response_text = json.dumps({
            "coaching_comment": "返答コメント",
            "daily_rating": "B",
            "progress_status": "進捗状況"
        })
        
        mock_client_instance = MagicMock()
        mock_genai_client.return_value = mock_client_instance
        mock_response_obj = MagicMock()
        mock_response_obj.text = mock_response_text
        mock_client_instance.models.generate_content.return_value = mock_response_obj
        
        response = self.client.post(
            url,
            data=json.dumps(payload),
            content_type='application/json'
        )
        
        self.assertEqual(response.status_code, 201)
        
        # trigger_summary=True のため、サマリー要約タスクが executor にサブミットされたことを確認
        mock_executor.submit.assert_called_once()
        # 最初の引数が update_session_summary_task 関数で、二番目の引数が session.id の文字列形式であることを確認
        args, kwargs = mock_executor.submit.call_args
        from api.views import update_session_summary_task
        self.assertEqual(args[0], update_session_summary_task)
        self.assertEqual(args[1], str(session.id))
