import uuid
from django.db import models

class Session(models.Model):
    """
    資格学習セッションを表すモデル
    """
    STATUS_CHOICES = [
        ('active', 'Active'),
        ('archived', 'Archived'),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    certification_name = models.CharField(
        max_length=255, 
        verbose_name="資格名",
        help_text="ユーザーが学習対象としている資格名 (例: 応用情報技術者, 基本情報技術者)"
    )
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="作成日時")
    status = models.CharField(
        max_length=20, 
        choices=STATUS_CHOICES, 
        default='active', 
        verbose_name="ステータス"
    )

    class Meta:
        db_table = 'sessions'
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['status', '-created_at']),
        ]

    def __str__(self):
        return f"{self.certification_name} ({self.status}) - {self.id}"


class Message(models.Model):
    """
    チャットの各メッセージ（送信者およびAI応答）を記録するモデル
    """
    ROLE_CHOICES = [
        ('user', 'User'),
        ('assistant', 'Assistant'),
    ]

    RATING_CHOICES = [
        ('A', 'A'),
        ('B', 'B'),
        ('C', 'C'),
        ('D', 'D'),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    session = models.ForeignKey(
        Session, 
        on_delete=models.CASCADE, 
        related_name='messages', 
        verbose_name="セッション"
    )
    sender_role = models.CharField(
        max_length=10, 
        choices=ROLE_CHOICES, 
        verbose_name="送信者ロール"
    )
    sent_at = models.DateTimeField(auto_now_add=True, verbose_name="送信日時")
    content = models.TextField(verbose_name="メッセージ本文")
    
    # 評価および進捗状況 (AIコーチから得られるフィードバック項目)
    rating = models.CharField(
        max_length=2, 
        choices=RATING_CHOICES, 
        blank=True, 
        null=True, 
        verbose_name="評価"
    )
    progress_status = models.TextField(
        blank=True, 
        null=True, 
        verbose_name="進捗状況",
        help_text="AIが判断した学習進捗や理解の深まり具合"
    )

    class Meta:
        db_table = 'messages'
        ordering = ['sent_at']
        indexes = [
            models.Index(fields=['session', 'sent_at']),
        ]

    def __str__(self):
        return f"[{self.sender_role}] {self.content[:30]}..."


class SessionSummary(models.Model):
    """
    会話から抽出した要約コンテキストを管理するモデル
    1つのセッションに対して1つの最新要約のみを保持する
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    session = models.OneToOneField(
        Session, 
        on_delete=models.CASCADE, 
        related_name='summary', 
        verbose_name="セッション"
    )
    summary_text = models.TextField(
        verbose_name="最新要約テキスト(Markdown)",
        help_text="つまずきポイント、理解度、アドバイスの要点をまとめたMarkdownテキスト"
    )
    updated_at = models.DateTimeField(auto_now=True, verbose_name="更新日時")

    class Meta:
        db_table = 'session_summaries'

    def __str__(self):
        return f"Summary for {self.session.certification_name} (Updated: {self.updated_at})"
