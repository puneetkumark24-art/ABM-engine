# DRIP Amazon SES receipt plane. Creation does not enable application sending.
variable "ses_sending_domain" { type = string }
variable "ses_mail_from_subdomain" { type = string, default = "bounce" }

resource "aws_sesv2_email_identity" "drip" {
  email_identity = var.ses_sending_domain
}

resource "aws_sesv2_email_identity_mail_from_attributes" "drip" {
  email_identity         = aws_sesv2_email_identity.drip.email_identity
  mail_from_domain       = "${var.ses_mail_from_subdomain}.${var.ses_sending_domain}"
  behavior_on_mx_failure = "REJECT_MESSAGE"
}

resource "aws_sesv2_configuration_set" "drip" {
  configuration_set_name = "drip-${var.env}"
  delivery_options { tls_policy = "REQUIRE" }
  reputation_options { reputation_metrics_enabled = true }
  suppression_options { suppressed_reasons = ["BOUNCE", "COMPLAINT"] }
}

resource "aws_sns_topic" "ses_events" {
  name              = "drip-${var.env}-ses-events"
  kms_master_key_id = "alias/aws/sns"
}

resource "aws_sqs_queue" "ses_events_dlq" {
  name                    = "drip-${var.env}-ses-events-dlq"
  sqs_managed_sse_enabled = true
  message_retention_seconds = 1209600
}

resource "aws_sqs_queue" "ses_events" {
  name                       = "drip-${var.env}-ses-events"
  sqs_managed_sse_enabled    = true
  visibility_timeout_seconds = 90
  message_retention_seconds  = 345600
  redrive_policy = jsonencode({
    deadLetterTargetArn = aws_sqs_queue.ses_events_dlq.arn
    maxReceiveCount     = 8
  })
}

data "aws_iam_policy_document" "ses_events_queue" {
  statement {
    sid       = "OnlyExactSesTopic"
    effect    = "Allow"
    actions   = ["sqs:SendMessage"]
    resources = [aws_sqs_queue.ses_events.arn]
    principals { type = "Service", identifiers = ["sns.amazonaws.com"] }
    condition {
      test     = "ArnEquals"
      variable = "aws:SourceArn"
      values   = [aws_sns_topic.ses_events.arn]
    }
  }
}

resource "aws_sqs_queue_policy" "ses_events" {
  queue_url = aws_sqs_queue.ses_events.id
  policy    = data.aws_iam_policy_document.ses_events_queue.json
}

resource "aws_sns_topic_subscription" "ses_events" {
  topic_arn            = aws_sns_topic.ses_events.arn
  protocol             = "sqs"
  endpoint             = aws_sqs_queue.ses_events.arn
  raw_message_delivery = false
}

resource "aws_sesv2_configuration_set_event_destination" "drip" {
  configuration_set_name = aws_sesv2_configuration_set.drip.configuration_set_name
  event_destination_name = "drip-sns"
  event_destination {
    enabled = true
    matching_event_types = [
      "SEND", "REJECT", "BOUNCE", "COMPLAINT", "DELIVERY",
      "RENDERING_FAILURE", "DELIVERY_DELAY", "SUBSCRIPTION"
    ]
    sns_destination { topic_arn = aws_sns_topic.ses_events.arn }
  }
}

data "aws_iam_policy_document" "drip_ses_sender" {
  statement {
    effect    = "Allow"
    actions   = ["ses:SendEmail"]
    resources = [aws_sesv2_email_identity.drip.arn]
  }
}

data "aws_iam_policy_document" "drip_ses_receipts" {
  statement {
    effect = "Allow"
    actions = ["sqs:ReceiveMessage", "sqs:DeleteMessage", "sqs:ChangeMessageVisibility", "sqs:GetQueueAttributes"]
    resources = [aws_sqs_queue.ses_events.arn]
  }
}

output "ses_configuration_set" { value = aws_sesv2_configuration_set.drip.configuration_set_name }
output "ses_event_topic_arn" { value = aws_sns_topic.ses_events.arn }
output "ses_event_queue_url" { value = aws_sqs_queue.ses_events.id }
output "ses_event_dlq_url" { value = aws_sqs_queue.ses_events_dlq.id }
output "ses_sender_policy_json" { value = data.aws_iam_policy_document.drip_ses_sender.json }
output "ses_receipt_policy_json" { value = data.aws_iam_policy_document.drip_ses_receipts.json }
