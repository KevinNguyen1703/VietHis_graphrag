"""
Reference:
 - Prompts are from [graphrag](https://github.com/microsoft/graphrag)
"""

GRAPH_FIELD_SEP = "<SEP>"
PROMPTS = {}

PROMPTS[
    "claim_extraction"
] = """-Hoạt động mục tiêu-
Bạn là trợ lý thông minh giúp người phân tích xử lý và phân tích các tuyên bố đối với các thực thể lịch sử trong tài liệu văn bản.

-Mục tiêu-
Dựa trên tài liệu văn bản, thông số thực thể, và mô tả tuyên bố, trích xuất các thực thể phù hợp và các tuyên bố liên quan đến chúng.

-Các bước-
1. Trích xuất tất cả các thực thể được đặt tên phù hợp với thông số kỹ thuật thực thể đã được xác định trước. Chi tiết thực thể có thể là một danh sách các tên thực thể hoặc một danh sách các loại thực thể.
- Đối với thực thể dạng sự kiện, hãy kèm với năm diễn ra. Ví dụ: Điện Biên Phủ (1954), Thành lập Mặt Trận Liên Việt (1951)
- Đối với thực thể dạng thời gian, hoặc khoảng thời gian chỉ cần giữ lại số năm. Ví dụ: 1958, 1963-1964 (cho khoảng thời gian), X-XII (cho khoảng thời gian dạng thế kỉ)
- Đối với thực thể dạng người hãy thêm các chức vụ (nếu có). Ví dụ: 'Chủ tịch Hồ Chí Minh' thay vì 'Hồ Chí Minh', 'Đại tướng Võ Nguyên Giáp' thay vì 'Võ Nguyên Giáp'
2. Đối với mỗi thực thể được xác định trong bước 1, trích xuất tất cả các tuyên bố liên quan đến thực thể đó. Các tuyên bố cần phải phù hợp với mô tả tuyên bố đã được xác định, và thực thể đó phải là chủ thể của tuyên bố. 
Các tuyên bố có thể bao gồm các ý nghĩa lịch sử, mục tiêu, nguyên nhân, nhiệm vụ (nếu có). Đối với mỗi tuyên bố, trích xuất thông tin sau:
- Subject: tên của thực thể là chủ thể của tuyên bố, viết hoa. Thực thể chủ thể là thực thể thực hiện hành động được mô tả trong tuyên bố. Chủ thể cần phải là một trong các thực thể đã được xác định trong bước 1.
- Object: tên của thực thể là đối tượng của tuyên bố, viết hoa. Thực thể đối tượng là thực thể mà hành động được mô tả trong tuyên bố ảnh hưởng đến hoặc xử lý. Nếu đối tượng không biết, sử dụng NONE.
- Claim Type: danh mục tổng thể của tuyên bố, viết hoa. Đặt tên sao cho có thể lặp lại trên nhiều đầu vào văn bản, để các tuyên bố tương tự có cùng một loại tuyên bố.
- Claim Status: TRUE, FALSE, hoặc SUSPECTED. TRUE có nghĩa là tuyên bố được xác nhận, FALSE có nghĩa là tuyên bố bị phát hiện là sai, SUSPECTED có nghĩa là tuyên bố chưa được xác minh.
- Claim Description: Mô tả chi tiết giải thích lý do đằng sau tuyên bố, cùng với tất cả các bằng chứng và tài liệu tham khảo liên quan.
- Claim Date: Khoảng thời gian (start_date, end_date) khi tuyên bố được đưa ra. Cả start_date và end_date đều phải ở định dạng ISO-8601. Nếu tuyên bố được đưa ra vào một ngày duy nhất thay vì một phạm vi ngày, đặt cùng ngày cho cả start_date và end_date. Nếu ngày không biết, trả về NONE.
- Claim Source Text: Danh sách tất cả các trích dẫn từ văn bản gốc liên quan đến tuyên bố.

Định dạng mỗi tuyên bố dưới dạng (<subject_entity>{tuple_delimiter}<object_entity>{tuple_delimiter}<claim_type>{tuple_delimiter}<claim_status>{tuple_delimiter}<claim_start_date>{tuple_delimiter}<claim_end_date>{tuple_delimiter}<claim_description>{tuple_delimiter}<claim_source>)

3. Trả về kết quả bằng tiếng Việt dưới dạng một danh sách duy nhất gồm tất cả các thực thể và mối quan hệ đã xác định ở bước 1 và 2. Sử dụng {record_delimiter} làm dấu phân cách cho danh sách.

4. Khi hoàn thành, xuất {completion_delimiter}

######################

######################
-Ví dụ-
######################
Ví dụ 1:
Entity specification: person
Claim description: ý nghĩa lịch sử của một người
Text: Theo bài viết ngày 01/06/1965, Hồ Chí Minh đã ký một sắc lệnh quan trọng nhằm tăng cường sức mạnh quốc phòng của Việt Nam trong bối cảnh chiến tranh. Sắc lệnh này đã giúp tăng cường sự chuẩn bị của quân đội và củng cố vị thế của Việt Nam trên trường quốc tế.

Output:

(CHỦ TỊCH HỒ CHÍ MINH{tuple_delimiter}VIỆT NAM{tuple_delimiter}Ý NGHĨA LỊCH SỬ{tuple_delimiter}TRUE{tuple_delimiter}1965-06-01T00:00:00{tuple_delimiter}1965-06-01T00:00:00{tuple_delimiter}Chủ tịch Hồ Chí Minh được biết đến là người đã ký một sắc lệnh quan trọng nhằm tăng cường sức mạnh quốc phòng của Việt Nam trong bối cảnh chiến tranh, góp phần củng cố vị thế quốc gia và quân đội theo bài viết ngày 01/06/1965{tuple_delimiter}Theo bài viết ngày 01/06/1965, Hồ Chí Minh đã ký một sắc lệnh quan trọng nhằm tăng cường sức mạnh quốc phòng của Việt Nam trong bối cảnh chiến tranh. Sắc lệnh này đã giúp tăng cường sự chuẩn bị của quân đội và củng cố vị thế của Việt Nam trên trường quốc tế.)
{completion_delimiter}


Ví dụ 2:
Entity specification: person, organization
Claim description: red flags associated with an entity
Text: Theo một bài viết ngày 01/07/1945, Đại tướng Võ Nguyên Giáp đã chỉ đạo các chiến lược quân sự quan trọng trong trận chiến Điện Biên Phủ. Ông cũng bị tuyên bố đã vi phạm chỉ thị của Bộ Chính trị trong một số quyết định chiến lược trong suốt cuộc kháng chiến chống Pháp.

Output:

(VÕ NGUYÊN GIÁP{tuple_delimiter}NONE{tuple_delimiter}STRATEGIC DECISIONS{tuple_delimiter}TRUE{tuple_delimiter}1945-07-01T00:00:00{tuple_delimiter}1945-07-01T00:00:00{tuple_delimiter}Võ Nguyên Giáp được biết đến với vai trò quan trọng trong việc chỉ đạo các chiến lược quân sự trong trận Điện Biên Phủ theo bài viết ngày 01/07/1945{tuple_delimiter}Theo một bài viết ngày 01/07/1945, Đại tướng Võ Nguyên Giáp đã chỉ đạo các chiến lược quân sự quan trọng trong trận chiến Điện Biên Phủ.)

{record_delimiter}

(VÕ NGUYÊN GIÁP{tuple_delimiter}NONE{tuple_delimiter}STRATEGIC VIOLATIONS{tuple_delimiter}SUSPECTED{tuple_delimiter}NONE{tuple_delimiter}NONE{tuple_delimiter}Võ Nguyên Giáp bị tuyên bố đã vi phạm chỉ thị của Bộ Chính trị trong một số quyết định chiến lược trong suốt cuộc kháng chiến chống Pháp{tuple_delimiter}Ông cũng bị tuyên bố đã vi phạm chỉ thị của Bộ Chính trị trong một số quyết định chiến lược trong suốt cuộc kháng chiến chống Pháp.)
{completion_delimiter}

-Real Data-
Sử dụng thông tin sau đây để trả lời
Entity specification: {entity_specs}
Claim description: {claim_description}
Text: {input_text}
Output:
"""

# PROMPTS[
#     "community_report"
# ] = """-Hoạt động mục tiêu-
# Bạn là trợ lý AI giúp người phân tích thực hiện khám phá thông tin tổng quát. Khám phá thông tin là quá trình xác định và đánh giá các thông tin liên quan đến các thực thể nhất định (ví dụ: tổ chức và cá nhân) trong một mạng lưới.
#
# -Mục tiêu-
# Viết một báo cáo toàn diện về một cộng đồng, dựa trên danh sách các thực thể thuộc cộng đồng đó cùng với các mối quan hệ và các tuyên bố liên quan (nếu có). Báo cáo này sẽ được sử dụng để cung cấp thông tin cho các nhà quyết định về cộng đồng và tác động tiềm ẩn của nó. Nội dung của báo cáo bao gồm tổng quan về các thực thể chính trong cộng đồng, sự tuân thủ pháp lý, khả năng kỹ thuật, danh tiếng, ý nghĩa lịch sử, ảnh hưởng và các tuyên bố đáng chú ý.
#
# -Cấu trúc báo cáo-
#
# Báo cáo sẽ bao gồm các phần sau:
#
# - TITLE: Tên cộng đồng đại diện cho các thực thể chính – tiêu đề ngắn gọn nhưng cụ thể. Khi có thể, bao gồm các thực thể đã được đặt tên đại diện trong tiêu đề.
# - SUMMARY: Tóm tắt tổng quan về cấu trúc cộng đồng, cách các thực thể liên kết với nhau và thông tin đáng chú ý liên quan đến các thực thể.
# - IMPACT SEVERITY RATING: Điểm số từ 0-10 thể hiện mức độ nghiêm trọng của tác động từ các thực thể trong cộng đồng. IMPACT là mức độ quan trọng của cộng đồng.
# - RATING EXPLANATION: Giải thích một câu về điểm số mức độ tác động.
# - DETAILED FINDINGS: Danh sách 5-10 thông tin quan trọng về cộng đồng. Mỗi thông tin có tóm tắt ngắn gọn và theo sau là nhiều đoạn văn giải thích chi tiết căn cứ theo các quy tắc dưới đây.
#
# Trả về kết quả dưới dạng chuỗi JSON được định dạng chính xác như sau:
#
#     {{
#         "title": <report_title>,
#         "summary": <executive_summary>,
#         "rating": <impact_severity_rating>,
#         "rating_explanation": <rating_explanation>,
#         "findings": [
#             {{
#                 "summary":<insight_1_summary>,
#                 "explanation": <insight_1_explanation>
#             }},
#             {{
#                 "summary":<insight_2_summary>,
#                 "explanation": <insight_2_explanation>
#             }}
#             ...
#         ]
#     }}
#
# -Các quy tắc-
#
# Các điểm được hỗ trợ bởi dữ liệu nên liệt kê các tài liệu tham khảo của chúng như sau:
#
# "Câu này là ví dụ được hỗ trợ bởi nhiều tài liệu tham khảo dữ liệu [Dữ liệu: <tên bộ dữ liệu> (mã bản ghi); <tên bộ dữ liệu> (mã bản ghi)]."
#
# Không liệt kê quá 5 mã bản ghi trong một tài liệu tham khảo. Thay vào đó, liệt kê 5 mã bản ghi có liên quan nhất và thêm "+more" để chỉ rằng còn nhiều hơn.
#
# Ví dụ: "Người X là chủ sở hữu của Công ty Y và đối mặt với nhiều tuyên bố sai phạm [Dữ liệu: Báo cáo (1), Thực thể (5, 7); Quan hệ (23); Các tuyên bố (7, 2, 34, 64, 46, +more)]."
#
# Trong đó, 1, 5, 7, 23, 2, 34, 46, và 64 là các mã bản ghi (không phải chỉ số).
#
# Không bao gồm thông tin nếu không có chứng cứ hỗ trợ.
#
# -Ví dụ đầu vào-
#
# Văn bản:
#
# Thực thể
#
# id, entity, description
# 5, VERDANT OASIS PLAZA, Verdant Oasis Plaza là địa điểm của Unity March
# 6, HARMONY ASSEMBLY, Harmony Assembly là tổ chức tổ chức cuộc diễu hành tại Verdant Oasis Plaza
#
# Quan hệ
#
# id, source, target, description
# 37, VERDANT OASIS PLAZA, UNITY MARCH, Verdant Oasis Plaza là địa điểm của Unity March
# 38, VERDANT OASIS PLAZA, HARMONY ASSEMBLY, Harmony Assembly tổ chức cuộc diễu hành tại Verdant Oasis Plaza
# 39, VERDANT OASIS PLAZA, UNITY MARCH, Unity March diễn ra tại Verdant Oasis Plaza
# 40, VERDANT OASIS PLAZA, TRIBUNE SPOTLIGHT, Tribune Spotlight đang đưa tin về cuộc diễu hành tại Verdant Oasis Plaza
# 41, VERDANT OASIS PLAZA, BAILEY ASADI, Bailey Asadi đang phát biểu tại Verdant Oasis Plaza về cuộc diễu hành
# 43, HARMONY ASSEMBLY, UNITY MARCH, Harmony Assembly tổ chức Unity March
#
# Đầu ra:
#
# {{
#     "title": "Verdant Oasis Plaza và Unity March",
#     "summary": "Cộng đồng xoay quanh Verdant Oasis Plaza, nơi diễn ra Unity March. Plaza có các mối quan hệ với Harmony Assembly, Unity March và Tribune Spotlight, tất cả đều liên quan đến sự kiện diễu hành.",
#     "rating": 5.0,
#     "rating_explanation": "Mức độ tác động trung bình do tiềm năng gây bất ổn hoặc xung đột trong Unity March.",
#     "findings": [
#         {{
#             "summary": "Verdant Oasis Plaza là địa điểm trung tâm",
#             "explanation": "Verdant Oasis Plaza là thực thể trung tâm trong cộng đồng này, phục vụ như địa điểm tổ chức Unity March. Plaza là mối liên kết chung giữa các thực thể khác, cho thấy tầm quan trọng của nó trong cộng đồng. Sự kết hợp của plaza với cuộc diễu hành có thể dẫn đến các vấn đề như trật tự công cộng hoặc xung đột, tùy thuộc vào tính chất của cuộc diễu hành và phản ứng của cộng đồng. [Data: Entities (5), Relationships (37, 38, 39, 40, 41, +more)]"
#         }},
#         {{
#             "summary": "Vai trò của Harmony Assembly trong cộng đồng",
#             "explanation": "Harmony Assembly là thực thể quan trọng trong cộng đồng này, là tổ chức tổ chức Unity March tại Verdant Oasis Plaza. Tính chất của Harmony Assembly và cuộc diễu hành của họ có thể là nguồn nguy cơ, tùy vào mục tiêu của họ và phản ứng mà nó gây ra. Quan hệ giữa Harmony Assembly và plaza là yếu tố quan trọng trong việc hiểu được động lực cộng đồng. [Data: Entities (6), Relationships (38, 43)]"
#         }},
#         {{
#             "summary": "Unity March là sự kiện quan trọng",
#             "explanation": "Unity March là một sự kiện quan trọng diễn ra tại Verdant Oasis Plaza. Sự kiện này là yếu tố quan trọng trong động lực cộng đồng và có thể là nguồn nguy cơ, tùy thuộc vào tính chất của cuộc diễu hành và phản ứng mà nó gây ra. Quan hệ giữa cuộc diễu hành và plaza là yếu tố quan trọng trong việc hiểu cộng đồng này. [Data: Relationships (39)]"
#         }},
#         {{
#             "summary": "Vai trò của Tribune Spotlight",
#             "explanation": "Tribune Spotlight đang đưa tin về Unity March diễn ra tại Verdant Oasis Plaza. Điều này cho thấy sự kiện đã thu hút sự chú ý của truyền thông, điều này có thể làm tăng tác động của nó đối với cộng đồng. Vai trò của Tribune Spotlight có thể quan trọng trong việc định hình nhận thức của công chúng về sự kiện và các thực thể liên quan. [Data: Relationships (40)]"
#         }}
#     ]
# }}
#
# # Dữ liệu thực
#
# Sử dụng văn bản sau cho câu trả lời của bạn. Không bịa ra bất cứ điều gì trong câu trả lời của bạn.
#
# Text:
# {input_text}
# Output:
#
# """

PROMPTS[
    "entity_extraction"
] = """Mục tiêu: Dựa trên văn bản liên quan đến hoạt động này và danh sách các loại thực thể, xác định tất cả các thực thể thuộc các loại đó trong văn bản và các mối quan hệ giữa các thực thể đã xác định.

Các bước:
1. Xác định tất cả các thực thể. Đối với mỗi thực thể đã xác định, trích xuất thông tin sau:
- entity_name: Tên thực thể, viết hoa
- entity_type: Một trong các loại sau: [{entity_types}]
- entity_time: Thời gian có mặt của thực thể. Có thể tự tạo ra tri thức nếu chắc chắn câu trả lời hoặc trả về 'None'. Kết quả sẽ được về dưới dạng: dd/mm/yyyy, mm/yyyy, yyyy hoặc None. Ví dụ: 2/9/1945, 3/1954, 1930, None
- entity_description: Mô tả chi tiết về đặc điểm và hoạt động của thực thể Định dạng mỗi thực thể dưới dạng ("entity"{tuple_delimiter}<entity_name>{tuple_delimiter}<entity_type>{tuple_delimiter}<entity_time>{tuple_delimiter}<entity_description>)
Yêu cầu:
- Đối với thực thể dạng sự kiện và các chiến lược, mô tả thực thể cần trích xuất đầy đủ và chi tiết các phần như ý nghĩa, mục đích, mục tiêu, những thuận lợi, khó khăn (nếu có).
- Đối với thực thể dạng người, nơi chốn mô tả thực thể cần trích xuất đầy đủ các phần như ý nghĩa, tác đụng của người đó đến các sự kiện.
- Nếu thực thể không có thời gian cụ thể thì trả về giá trị NA
- Đối với thực thể dạng người hãy thêm các chức vụ (nếu có). Ví dụ: 'Chủ tịch Hồ Chí Minh' thay vì 'Hồ Chí Minh', 'Đại tướng Võ Nguyên Giáp' thay vì 'Võ Nguyên Giáp'
2. Từ các thực thể đã xác định ở bước 1, xác định tất cả các cặp (source_entity, target_entity) có mối quan hệ rõ ràng với nhau. Đối với mỗi cặp thực thể liên quan, trích xuất thông tin sau:
- source_entity: Tên thực thể nguồn, như đã xác định ở bước 1
- target_entity: Tên thực thể mục tiêu, như đã xác định ở bước 1
- relationship_description: Giải thích lý do tại sao thực thể nguồn và thực thể mục tiêu có mối quan hệ với nhau. Mối quan hệ này có thể bao gồm các tác động lịch sử lẫn nhau. Phải chỉ rõ tác đụng của thực thể này đến thực thể kia.
- relationship_strength: Điểm số số học chỉ mức độ mạnh mẽ của mối quan hệ giữa thực thể nguồn và thực thể mục tiêu Định dạng mỗi mối quan hệ dưới dạng ("relationship"{tuple_delimiter}<source_entity>{tuple_delimiter}<target_entity>{tuple_delimiter}<relationship_description>{tuple_delimiter}<relationship_strength>)

3. Trả về kết quả bằng tiếng Việt dưới dạng một danh sách duy nhất gồm tất cả các thực thể và mối quan hệ đã xác định ở bước 1 và 2. Sử dụng {record_delimiter} làm dấu phân cách cho danh sách.

4. Khi hoàn thành, xuất {completion_delimiter}

######################

######################
-Ví dụ-
######################

Ví dụ 1:
Entity_types: [person,event,place,opponent,component,action,strategy] 
Text:
Cuộc kháng chiến chống Pháp chuyển sang giai đoạn mới: Pháp buộc phải chuyển từ ”đánh nhanh thắng nhanh” sang ”đánh lâu dài” với ta, thực hiện chính sách ”Dùng người Việt đánh người Việt,lấy chiến tranh nuôi chiến tranh ”

Kết quả: ("entity"{tuple_delimiter}"Pháp"{tuple_delimiter}"opponent"{tuple_delimiter}1945-1954{tuple_delimiter}"Thực dân Pháp là một đế quốc xâm lược và cai trị tàn bạo, đặc biệt tại các quốc gia thuộc địa như Việt Nam. Họ áp đặt chính sách chia để trị và khai thác tài nguyên, duy trì quyền lực qua các biện pháp khắc nghiệt. Trong chiến tranh Đông Dương, Pháp buộc phải chuyển từ chiến lược 'đánh nhanh thắng nhanh' sang 'đánh lâu dài' khi đối mặt với sức mạnh kháng chiến của người Việt.."){record_delimiter} 
("entity"{tuple_delimiter}"đánh nhanh thắng nhanh"{tuple_delimiter}"strategy"{tuple_delimiter}1947{tuple_delimiter}"'Đánh nhanh thắng nhanh' là chiến lược quân sự mà Thực dân Pháp áp dụng trong giai đoạn đầu chiến tranh Đông Dương, nhằm tiêu diệt nhanh chóng lực lượng kháng chiến của ta bằng các đòn tấn công mạnh mẽ, quyết liệt. Tuy nhiên, chiến lược này đã thất bại khi đối mặt với sự kiên cường và quyết tâm của quân đội ta, buộc Pháp phải chuyển sang chiến lược 'đánh lâu dài'."){record_delimiter} 
("entity"{tuple_delimiter}"đánh lâu dài"{tuple_delimiter}"strategy"{tuple_delimiter}1947{tuple_delimiter}"'Đánh lâu dài' là chiến lược mà Thực dân Pháp chuyển sang trong giai đoạn sau của chiến tranh Đông Dương, khi nhận thấy thất bại trong chiến lược 'đánh nhanh thắng nhanh' Pháp buộc phải đối phó với kháng chiến mạnh mẽ của ta bằng cách duy trì chiến tranh kéo dài, thực hiện chính sách 'Dùng người Việt đánh người Việt' và 'lấy chiến tranh nuôi chiến tranh' để duy trì lực lượng và làm suy yếu tinh thần kháng chiến."){record_delimiter} 
("entity"{tuple_delimiter}"Dùng người Việt đánh người Việt, lấy chiến tranh nuôi chiến tranh"{tuple_delimiter}"strategy"{tuple_delimiter}1947{tuple_delimiter}"'Dùng người Việt đánh người Việt, lấy chiến tranh nuôi chiến tranh' là chính sách của Thực dân Pháp nhằm lợi dụng sự chia rẽ trong xã hội Việt Nam, sử dụng tài nguyên và sức lực của người dân để duy trì chiến tranh và kéo dài sự chiếm đóng."){record_delimiter} 
("relationship"{tuple_delimiter}"Pháp"{tuple_delimiter}"đánh nhanh thắng nhanh"{tuple_delimiter}"Pháp hy vọng tiêu diệt nhanh chóng lực lượng kháng chiến của ta bằng các cuộc tấn công mạnh mẽ và quyết liệt, nhằm kết thúc chiến tranh sớm. Tuy nhiên, chiến lược này đã thất bại khi phải đối mặt với sức kháng cự mạnh mẽ và sự kiên cường của quân đội ta."{tuple_delimiter}8){record_delimiter} 
("relationship"{tuple_delimiter}"Pháp"{tuple_delimiter}"đánh lâu dài"{tuple_delimiter}"phản ánh sự chuyển hướng chiến lược của Thực dân Pháp sau khi chiến lược "đánh nhanh thắng nhanh" thất bại. Khi đối mặt với kháng chiến mạnh mẽ của ta, Pháp buộc phải kéo dài chiến tranh, áp dụng chiến lược 'đánh lâu dài' để duy trì sự kiểm soát, sử dụng tài nguyên và sức lực của người dân Việt Nam trong suốt cuộc chiến."{tuple_delimiter}7){record_delimiter} 
("relationship"{tuple_delimiter}"Pháp"{tuple_delimiter}"Dùng người Việt đánh người Việt,lấy chiến tranh nuôi chiến tranh"{tuple_delimiter}chính sách của Pháp nhằm lợi dụng sự chia rẽ trong xã hội Việt Nam, sử dụng người Việt để chiến đấu chống lại nhau và tận dụng tài nguyên của dân để duy trì chiến tranh, kéo dài sự chiếm đóng"{tuple_delimiter}9){completion_delimiter}
("relationship"{tuple_delimiter}"đánh nhanh thắng nhanh"{tuple_delimiter}"đánh lâu dài"{tuple_delimiter}"sự chuyển đổi chiến lược của Pháp trong chiến tranh Đông Dương. Khi chiến lược "đánh nhanh thắng nhanh" thất bại trước sức kháng cự mạnh mẽ của ta, Pháp phải chuyển sang "đánh lâu dài" để duy trì cuộc chiến và đối phó với phong trào kháng chiến, hy vọng tiêu hao sức lực của đối phương và kéo dài sự chiếm đóng."{tuple_delimiter}8){record_delimiter} 

###################### Dữ liệu thực tế ###################### 
Entity_types: {entity_types} 
Text: {input_text} 
###################### 
Output:
"""


PROMPTS[
    "summarize_entity_descriptions"
] = """Bạn là một trợ lý hữu ích có nhiệm vụ tạo ra một bản tóm tắt đầy đủ từ dữ liệu dưới đây. 
Khi được cung cấp một hoặc hai thực thể cùng với danh sách mô tả, tất cả đều liên quan đến cùng một thực thể hoặc nhóm thực thể, 
Hãy chắc chắn bao gồm thông tin từ tất cả các mô tả. Đảm bảo các ý nghĩa lịch sử của đối tượng được giữ sau quá trình tổng hợp.
Nếu các phần thông tin bị trùng lặp thì hãy loại bỏ các thông tin bị trùng lặp nhưng vẫn giữa cấu trúc của văn bản tóm tắt. (Ví dụ có 2 đoạn mô tả đều cùng mô tả về ý nghĩa, mục đích, mục tiêu của thực thể, thì vẫn giữ nguyên cấu trúc gồm ý nghĩa, mục đích, mục tiêu của thực thể nhưng tổng hợp 2 đoạn mô tả trên thành 1)
Nếu các mô tả cung cấp thông tin mâu thuẫn, hãy giải quyết sự mâu thuẫn đó và đưa ra một bản tóm tắt thống nhất, hợp lý. 
Lưu ý rằng mô tả cần được viết ở ngôi thứ ba và bao gồm tên của các thực thể để có đầy đủ bối cảnh.
#######
-Data-
Entities: {entity_name}
Description List: {description_list}
#######
Output:

"""

PROMPTS[
    "merge_entity"
] = """Bạn là một trợ lý hữu ích có nhiệm vụ gom nhóm các thực thể lịch sử giống nhau. 
Bạn sẽ được cung cấp chuỗi các thực thể về chủ đề lịch sử, Nhiệm vụ của bạn là chỉ ra các thực thể giống nhau nhưng khác cách biểu diễn.
Kết quả ngõ ra sẽ có dạng danh sách của các cặp thực thể trùng nhau đồng thời đề xuất tên gọi cố định cho nhóm thực thể đó. Định dạng ngõ ra như sau:
["thực thể 1","thực thể 2","thực thể 3"]-->"tên gọi được chọn cho nhóm thực thể"<SEP>
["thực thể 5","thực thể 6"]-->"tên gọi được chọn cho nhóm thực thể"
Yêu cầu:
- Các thực thể trùng nhau là các thực thể giống nhau nhưng được diễn đạt bằng các cách khác nhau.
- Tên gọi được chọn cho nhóm thực thể phải thể hiên được nội dung đầy đủ của các thực thể con
######################
-Ví dụ-
######################
Đầu vào:
HIỆP HỘI CÁC NƯỚC ĐÔNG NAM Á (ASEAN),HỘI NGHỊ IANTA (2-1945),RU DƠ VEN,ĐÁNH NHANH THẮNG NHANH,SỚC SIN,XTALIN,IANTA,TIÊU DIỆT CHỦ NGHĨA PHÁT XÍT ĐỨC VÀ QUÂN PHIỆT NHẬT,TRẬT TỰ HAI CỰC IANTA,MỸ,HỒ CHÍ MINH,CHỦ TỊCH HỒ CHÍ MINH,ANH,HỘI NGHỊ I-AN-TA,LIÊN XÔ,LIÊN HIỆP QUỐC,ĐÔNG ĐỨC,ĐÔNG ÂU,TÂY ĐỨC,TÂY ÂU,MÔNG CỔ,BẮC TRIỀU TIÊN,NAM XA-KHA-LIN,CU-RIN,NHẬT BẢN,NAM TRIỀU TIÊN,ASEAN,ĐÔNG NAM Á,NAM Á,TÂY Á,CHIẾN LƯỢC ĐÁNH NHANH THẮNG NHANH
Kết quả:
[HỘI NGHỊ IANTA (2-1945),IANTA,HỘI NGHỊ I-AN-TA]-->HỘI NGHỊ IANTA<SEP>
[ĐÁNH NHANH THẮNG NHANH, CHIẾN LƯỢC ĐÁNH NHANH THẮNG NHANH]-->CHIẾN LƯỢC ĐÁNH NHANH THẮNG NHANH<SEP>
[HIỆP HỘI CÁC NƯỚC ĐÔNG NAM Á (ASEAN), ASEAN]-->HIỆP HỘI CÁC NƯỚC ĐÔNG NAM Á (ASEAN)<SEP>
[HỒ CHÍ MINH,CHỦ TỊCH HỒ CHÍ MINH]-->CHỦ TỊCH HỒ CHÍ MINH
######################
-Data-
{entity_list}
#######
Output:

"""
PROMPTS[
    "time_extraction"
] = """Bạn là một trợ lý hỗ trợ trích xuất khoảng thời gian thích hợp để lọc các thông tin từ cơ sở dữ liệu cho quá trình retrival cho mô hình RAG.
Dựa vào câu hỏi được cung cấp hãy xác định khoảng thời gian mà sự kiện đang diễn ra.
Nếu trong câu hỏi không xác định khoảng thời gian, bạn hãy dựa vào kiến thức sẵn có để xác định thời gian phù hợp
Kết quả trả về dưới dạng cặp thời gian (thời gian bắt đầu-thời gian kết thúc). Định dạng thời gian có các dạng sau: dd/mm/yyyy, mm/yyyy, yyyy.
---------------------------
Ví dụ 1:
Input: 
"Chiến thắng nào dưới đây khẳng định quân dân miền Nam Việt Nam có khả năng đánh thắng chiến lược “Chiến tranh đặc biệt” (1961-1965) của Mỹ?
A. An Lão (Bình Định).	
B. Ba Gia (Quảng Ngãi),
c. Bình Giã (Bà Rịa).	
D. Ấp Bắc (Mĩ Tho)."
Output:
1961-1965
---------------------------
Ví dụ 2:
Input:
"Quan điểm đổi mới đất nước cùa Đảng Cộng sản Việt Nam (từ tháng 12-1986) không có nội dung nào dưới đây?
A.	Lấy đổi mới chính trị làm trọng tâm.
B.	Đi lên chủ nghĩa xã hội bằng những biện pháp phù hợp. 
C.	Không thay đổi mục tiêu của chù nghĩa xã hội.
D. Đổi mới toàn diện và đồng bộ."
Output:
12/1986-12/1986

###################### Dữ liệu thực tế ###################### 
-Input-
{query}
#######
Output:
"""

PROMPTS[
    "entiti_continue_extraction"
] = """NHIỀU thực thể đã bị bỏ sót trong lần trích xuất cuối cùng. Thêm chúng bên dưới bằng cùng một định dạng:
"""

PROMPTS[
    "entiti_if_loop_extraction"
] = """Có vẻ như một số thực thể vẫn còn bị bỏ sót. Trả lời yes | no nếu vẫn còn thực thể cần được thêm vào.
"""

PROMPTS["DEFAULT_ENTITY_TYPES"] = ["person","organization","event","place","action","strategy","impact"]
PROMPTS["DEFAULT_TUPLE_DELIMITER"] = "<|>"
PROMPTS["DEFAULT_RECORD_DELIMITER"] = "##"
PROMPTS["DEFAULT_COMPLETION_DELIMITER"] = "<|COMPLETE|>"

# PROMPTS[
#     "local_rag_response"
# ] = """---Role---
#
# You are a helpful assistant responding to questions about data in the tables provided.
#
#
# ---Goal---
#
# Generate a response of the target length and format that responds to the user's question, summarizing all information in the input data tables appropriate for the response length and format, and incorporating any relevant general knowledge.
# If you don't know the answer, just say so. Do not make anything up.
# Do not include information where the supporting evidence for it is not provided.
#
# ---Target response length and format---
#
# {response_type}
#
#
# ---Data tables---
#
# {context_data}
#
#
# ---Goal---
#
# Generate a response of the target length and format that responds to the user's question, summarizing all information in the input data tables appropriate for the response length and format, and incorporating any relevant general knowledge.
#
# If you don't know the answer, just say so. Do not make anything up.
#
# Do not include information where the supporting evidence for it is not provided.
#
#
# ---Target response length and format---
#
# {response_type}
#
# Add sections and commentary to the response as appropriate for the length and format. Style the response in markdown.
# """

PROMPTS[
    "local_rag_response"
] = """---Role---
Bạn là một trợ lý trả lời các câu hỏi trắc nghiệm về chủ đề lịch sử.

---Dữ liệu tăng cường---
{context_data}

---Goal---
Dựa vào kiến thức bạn đã có và dữ liệu được cung cấp để trả lời các câu trắc nghiệm sau
Nếu bạn không biết câu trả lời, chỉ cần nói vậy. Không bịa ra bất cứ điều gì.
Không bao gồm thông tin mà không cung cấp bằng chứng hỗ trợ cho thông tin đó.

"""

PROMPTS[
    "global_map_rag_points"
] = """---Role---

You are a helpful assistant responding to questions about data in the tables provided.


---Goal---

Generate a response consisting of a list of key points that responds to the user's question, summarizing all relevant information in the input data tables.

You should use the data provided in the data tables below as the primary context for generating the response.
If you don't know the answer or if the input data tables do not contain sufficient information to provide an answer, just say so. Do not make anything up.

Each key point in the response should have the following element:
- Description: A comprehensive description of the point.
- Importance Score: An integer score between 0-100 that indicates how important the point is in answering the user's question. An 'I don't know' type of response should have a score of 0.

The response should be JSON formatted as follows:
{{
    "points": [
        {{"description": "Description of point 1...", "score": score_value}},
        {{"description": "Description of point 2...", "score": score_value}}
    ]
}}

The response shall preserve the original meaning and use of modal verbs such as "shall", "may" or "will".
Do not include information where the supporting evidence for it is not provided.


---Data tables---

{context_data}

---Goal---

Generate a response consisting of a list of key points that responds to the user's question, summarizing all relevant information in the input data tables.

You should use the data provided in the data tables below as the primary context for generating the response.
If you don't know the answer or if the input data tables do not contain sufficient information to provide an answer, just say so. Do not make anything up.

Each key point in the response should have the following element:
- Description: A comprehensive description of the point.
- Importance Score: An integer score between 0-100 that indicates how important the point is in answering the user's question. An 'I don't know' type of response should have a score of 0.

The response shall preserve the original meaning and use of modal verbs such as "shall", "may" or "will".
Do not include information where the supporting evidence for it is not provided.

The response should be JSON formatted as follows:
{{
    "points": [
        {{"description": "Description of point 1", "score": score_value}},
        {{"description": "Description of point 2", "score": score_value}}
    ]
}}
"""

PROMPTS[
    "global_reduce_rag_response"
] = """---Role---

You are a helpful assistant responding to questions about a dataset by synthesizing perspectives from multiple analysts.


---Goal---

Generate a response of the target length and format that responds to the user's question, summarize all the reports from multiple analysts who focused on different parts of the dataset.

Note that the analysts' reports provided below are ranked in the **descending order of importance**.

If you don't know the answer or if the provided reports do not contain sufficient information to provide an answer, just say so. Do not make anything up.

The final response should remove all irrelevant information from the analysts' reports and merge the cleaned information into a comprehensive answer that provides explanations of all the key points and implications appropriate for the response length and format.

Add sections and commentary to the response as appropriate for the length and format. Style the response in markdown.

The response shall preserve the original meaning and use of modal verbs such as "shall", "may" or "will".

Do not include information where the supporting evidence for it is not provided.


---Target response length and format---

{response_type}


---Analyst Reports---

{report_data}


---Goal---

Generate a response of the target length and format that responds to the user's question, summarize all the reports from multiple analysts who focused on different parts of the dataset.

Note that the analysts' reports provided below are ranked in the **descending order of importance**.

If you don't know the answer or if the provided reports do not contain sufficient information to provide an answer, just say so. Do not make anything up.

The final response should remove all irrelevant information from the analysts' reports and merge the cleaned information into a comprehensive answer that provides explanations of all the key points and implications appropriate for the response length and format.

The response shall preserve the original meaning and use of modal verbs such as "shall", "may" or "will".

Do not include information where the supporting evidence for it is not provided.


---Target response length and format---

{response_type}

Add sections and commentary to the response as appropriate for the length and format. Style the response in markdown.
"""

PROMPTS[
    "naive_rag_response"
] = """You're a helpful assistant
Below are the knowledge you know:
{content_data}
---
If you don't know the answer or if the provided knowledge do not contain sufficient information to provide an answer, just say so. Do not make anything up.
Generate a response of the target length and format that responds to the user's question, summarizing all information in the input data tables appropriate for the response length and format, and incorporating any relevant general knowledge.
If you don't know the answer, just say so. Do not make anything up.
Do not include information where the supporting evidence for it is not provided.
---Target response length and format---
{response_type}
"""

PROMPTS["fail_response"] = "Sorry, I'm not able to provide an answer to that question."

PROMPTS["process_tickers"] = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"]

PROMPTS["default_text_separator"] = [
    # Paragraph separators
    "\n\n",
    "\r\n\r\n",
    # Line breaks
    "\n",
    "\r\n",
    # Sentence ending punctuation
    "。",  # Chinese period
    "．",  # Full-width dot
    ".",  # English period
    "！",  # Chinese exclamation mark
    "!",  # English exclamation mark
    "？",  # Chinese question mark
    "?",  # English question mark
    # Whitespace characters
    " ",  # Space
    "\t",  # Tab
    "\u3000",  # Full-width space
    # Special characters
    "\u200b",  # Zero-width space (used in some Asian languages)
]
