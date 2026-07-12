from scoreform import templates


class RecordingCanvas:
    def __init__(self):
        self.text = []

    def setFont(self, *_args): pass
    def setLineWidth(self, *_args): pass
    def rect(self, *_args, **_kwargs): pass
    def drawImage(self, *_args): pass
    def drawString(self, _x, _y, value): self.text.append(value)


def test_second_page_uses_global_labels_context_and_qr(monkeypatch):
    payloads = []
    monkeypatch.setattr(templates, "make_qr_image", lambda payload: payloads.append(payload) or object())
    canvas = RecordingCanvas()
    assignment = {"assignment_id": "quiz", "title": "Quiz", "question_count": 16}
    student = {"class_id": "class1", "student_id": "1001"}

    assert templates.draw_student_answer_sheet_page(canvas, assignment, student, 2)
    assert "Page 2 of 2" in canvas.text
    assert "Questions 16-16" in canvas.text
    assert "16." in canvas.text
    assert "15." not in canvas.text
    assert payloads == ["PDS1|module=scoreform|class=class1|aid=quiz|sid=1001|page=2"]
