"""URLs of the correspondence staff screens (2B.4, M9), mounted at /staff/p2/ before the read-only admin."""

from django.urls import path

from . import staff_views as v

app_name = "correspondence_staff"
urlpatterns = [
    path("", v.queue, name="queue"),
    path("items/<uuid:public_id>/", v.item_detail, name="item"),
    path("items/<uuid:public_id>/resolve/", v.resolve, name="resolve"),
    path("items/<uuid:public_id>/send-decision/", v.send_decision, name="send_decision"),
    path("cursors/<uuid:public_id>/restart/", v.restart, name="restart"),
    path("replies/<uuid:public_id>/", v.reply_detail, name="reply"),
    path("replies/<uuid:public_id>/confirm/", v.confirm_outcome, name="confirm_outcome"),
    path("replies/<uuid:public_id>/close/", v.close_reply, name="close_reply"),
    path("applications/", v.application_list, name="applications"),
    path("applications/<uuid:public_ref>/", v.application_detail, name="application"),
    path("applications/<uuid:public_ref>/pause/", v.pause, name="pause"),
    path("applications/<uuid:public_ref>/resume/", v.resume, name="resume"),
    path("applications/<uuid:public_ref>/message/preview/", v.preview_message, name="preview_message"),
    path("applications/<uuid:public_ref>/verification/resend/", v.resend_verification, name="resend_verification"),  # 9kg.50
    path("drafts/<uuid:public_id>/confirm/", v.confirm_message, name="confirm_message"),
    path("questions/<uuid:public_id>/approve/", v.approve, name="approve"),
    path("questions/<uuid:public_id>/withdraw/", v.withdraw, name="withdraw"),
    path("templates/", v.template_list, name="templates"),
    path("templates/<int:pk>/", v.template_detail, name="template"),
    path("templates/<int:pk>/approve/", v.approve_template, name="approve_template"),
]
