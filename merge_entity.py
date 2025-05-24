import psycopg2
from psycopg2 import sql
import hashlib
from datetime import datetime

# Connection parameters
host = "localhost"
port = "5432"
database = "history"
user = "postgres"
password = "postgres"


# Function to connect to the PostgreSQL database
def get_connection():
    return psycopg2.connect(
        host=host,
        port=port,
        dbname=database,
        user=user,
        password=password
    )


# Function to compute mdhash_id (simulating your compute_mdhash_id method)
def compute_mdhash_id(entity_name, prefix="ent-"):
    hash_object = hashlib.md5((prefix + entity_name).encode())
    return hash_object.hexdigest()


# Function to handle various date formats
def parse_date(date_str):
    if date_str is None or date_str.lower() == 'none':  # Handle None and 'None'
        return None

    # Try different date formats
    date_formats = [
        "%Y",  # Year only (e.g., 1945)
        "%d/%m/%Y",  # Day/Month/Year (e.g., 2/9/1945)
        "%m/%Y",  # Month/Year (e.g., 9/1945)
        "%Y-%m-%d",  # Standard ISO format (e.g., 1945-09-02)
    ]

    for date_format in date_formats:
        try:
            return datetime.strptime(date_str, date_format)
        except ValueError:
            continue

    # If none of the formats match, return None
    return None


# Function to create the events table if it does not exist
def create_table():
    connection = None
    cursor = None
    try:
        connection = get_connection()
        cursor = connection.cursor()

        create_table_query = '''
        CREATE TABLE IF NOT EXISTS events (
            entity_hash_id TEXT PRIMARY KEY,
            entity_name VARCHAR(255) NOT NULL,
            entity_time TIMESTAMP,
            entity_description TEXT
        );
        '''
        cursor.execute(create_table_query)
        connection.commit()
        print("Table 'events' is ready (created if not exists).")

    except Exception as e:
        print(f"Error creating table: {e}")

    finally:
        if cursor:
            cursor.close()
        if connection:
            connection.close()


# Function to insert rows with hash as primary key
def insert_rows(all_entities_data):
    connection = None
    cursor = None
    connection = get_connection()
    cursor = connection.cursor()

    # Prepare the data for insertion with hash as the primary key
    # data_for_postgres = [
    #     (
    #         key,
    #         all_entities_data[key]["entity_name"],
    #         parse_date(all_entities_data[key]["entity_time"]),  # Handle various date formats
    #         all_entities_data[key]["content"][len(all_entities_data[key]["entity_name"]):]
    #     )
    #     for key in all_entities_data.keys()
    # ]
    data_for_postgres=all_entities_data
    insert_query = '''
    INSERT INTO events (entity_hash_id, entity_name, entity_time, entity_description)
    VALUES (%s, %s, %s, %s)
    ON CONFLICT (entity_hash_id)
    DO UPDATE SET 
        entity_name = EXCLUDED.entity_name,
        entity_time = EXCLUDED.entity_time,
        entity_description = EXCLUDED.entity_description;
    '''

    cursor.executemany(insert_query, data_for_postgres)
    connection.commit()
    print(f"Inserted/Updated {len(all_entities_data)} rows.")



# Example usage
if __name__ == "__main__":
    # Ensure the table is created
    create_table()

    # Example data to insert (structure similar to your vector DB code)
    all_entities_data = [('ent-75f02eb248ea9f9c8cbb11bd28de19f9', 'ĐẠI HỘI LẦN VII - QUỐC TẾ CỘNG SẢN', None, 'Đại hội lần VII - Quốc tế Cộng sản diễn ra vào tháng 7 năm 1935, là một dịp quan trọng trong lịch sử phong trào cộng sản quốc tế, xác định nhiệm vụ chống lại chủ nghĩa phát xít, đấu tranh giành dân chủ và bảo vệ hòa bình. Đại hội này đã thúc đẩy sự hình thành Mặt trận nhân dân rộng rãi.<SEP>Đại hội lần VII - Quốc tế Cộng sản là một sự kiện quan trọng diễn ra vào tháng 7 năm 1935, tại đó đã xác định nhiệm vụ chống lại chủ nghĩa phát xít, thúc đẩy đấu tranh giành dân chủ và bảo vệ hòa bình. Đây là một bước đi quan trọng trong sự nghiệp quốc tế của phong trào cộng sản và cách mạng ở nhiều quốc gia, bao gồm cả Việt Nam.<SEP>Đảng Cộng sản Đông Dương là đảng chính trị mạnh nhất trong phong trào cách mạng Việt Nam thời bấy giờ, có tổ chức chặt chẽ và chủ trương rõ ràng. Đảng đã lãnh đạo nhân dân tham gia đấu tranh vì tự do và độc lập, đồng thời cũng là phần quan trọng trong sự chuyển biến chính trị tại Việt Nam dưới sự cai trị của thực dân Pháp.'), ('ent-a0f3c544b4d921ba7f3fbd01762af62d', 'MẶT TRẬN NHÂN DÂN', None, 'Mặt trận nhân dân là một liên minh chính trị tại Pháp, đã lên cầm quyền vào tháng 6 năm 1936. Mặt trận này thực hiện nhiều cải cách tiến bộ, đặc biệt là tại các thuộc địa như Đông Dương, nơi mà họ cử phái đoàn sang điều tra tình hình và nới rộng quyền tự do báo chí, tạo thuận lợi cho phong trào cách mạng tại Việt Nam.<SEP>Mặt trận nhân dân là một liên minh chính trị được thành lập tại Pháp vào tháng 6 năm 1936, nhằm thi hành các cải cách tiến bộ, bảo vệ quyền lợi của nhân dân và chống lại các lực lượng phản động, bao gồm sự phản kháng đối với chính sách cũ của chính phủ thực dân tại các thuộc địa như Đông Dương.<SEP>Đảng cách mạng là một trong những đảng phái chính trị hoạt động tại Đông Dương trong những năm 30 của thế kỷ XX. Họ tham gia vào phong trào đấu tranh cho quyền lợi của nhân dân và đứng trong hàng ngũ các đảng phái tiến bộ, nhưng không mạnh mẽ như Đảng Cộng sản Đông Dương.'), ('ent-ce86930a476aeca0fb790294fbb15528', 'PHÁP', None, 'Pháp là một quốc gia thực dân lớn vào những năm 30 của thế kỷ XX, đã có nhiều chính sách và biện pháp nhằm duy trì quyền kiểm soát đối với các thuộc địa như Đông Dương, bao gồm việc cử phái đoàn sang điều tra tình hình và thực hiện cải cách.<SEP>Pháp là quốc gia bị Đức tấn công và buộc phải đầu hàng trong Chiến tranh thế giới thứ hai. Sự đầu hàng này dẫn đến việc Pháp phải thực hiện chính sách thù địch với các lực lượng tiến bộ trong Việt Nam và gia tăng sự bóc lột người dân Việt Nam.<SEP>Pháp là thực dân đã thống trị Việt Nam trong thời kỳ này, là đối tượng chính của các phong trào đấu tranh chính trị. Chính sách đàn áp và bóc lột của thực dân Pháp đã thúc đẩy các phong trào yêu nước và đòi quyền sống trong nhân dân.<SEP>Trực thuộc vào chế độ thực dân ở Đông Dương, Pháp đã chịu sự thất bại trong Chiến tranh thế giới thứ hai và giờ đây đang bị Nhật Bản đô hộ. Ngày 9/3/1945, Pháp phải đầu hàng Nhật Bản cáng khiến tình hình chính trị tại Việt Nam bị xáo trộn.<SEP>Pháp là quốc gia thực dân thống trị Đông Dương vào những năm 30 của thế kỷ XX. Họ đã áp đặt nhiều chính sách đàn áp và khai thác tài nguyên, gây ra tình trạng bất bình trong nhân dân Việt Nam, nhưng đồng thời cũng tạo ra những điều kiện để các phong trào đấu tranh giành độc lập hình thành.<SEP>Thế lực phát xít là những chính quyền độc tài tại các quốc gia như Đức, Ý và Nhật Bản vào những năm 30 của thế kỷ XX, đã gây ra nhiều xung đột và đang chuẩn bị cho chiến tranh thế giới, ảnh hưởng sâu rộng đến tình hình chính trị và xã hội toàn cầu.'), ('ent-69ef3b0f8018c3240db7644848cd46bf', 'CHỐNG CHỦ NGHĨA PHÁT XÍT', None, 'Chống chủ nghĩa phát xít là một chiến lược quan trọng được xác định tại Đại hội lần VII - Quốc tế Cộng sản vào tháng 7 năm 1935, nhằm đáp ứng với sự trỗi dậy của các thế lực phát xít ở châu Âu. Mục tiêu của chiến lược này là bảo vệ hòa bình, thúc đẩy dân chủ và lật đổ các chế độ độc tài phát xít.<SEP>Đấu tranh giành dân chủ là một phần trong nhiệm vụ được xác định tại Đại hội lần VII - Quốc tế Cộng sản. Chiến lược này hướng tới việc nâng cao quyền lợi và tự do cho nhân dân, đồng thời đem lại một nền chính trị công bằng hơn thông qua việc tham gia vào các cuộc cách mạng và phong trào đòi tự do.'), ('ent-6036f18d2cbb8bf41c1d9135067f215f', 'TẠO THUẬN LỢI CHO CÁCH MẠNG VIỆT NAM', None, 'Tạo thuận lợi cho cách mạng Việt Nam là mục tiêu của Mặt trận nhân dân khi lên cầm quyền ở Pháp vào tháng 6 năm 1936. Bằng cách nới rộng quyền tự do báo chí và cử các phái đoàn sang điều tra tình hình Đông Dương, chính phủ này đã tạo ra nhiều cơ hội cho các phong trào cách mạng ở Việt Nam phát triển.'), ('ent-7b66f009a12edb18d986a3215aae4031', 'NHỮNG NĂM 30 CỦA THẾ KỶ XX', None, 'Những năm 30 của thế kỷ XX là thời kỳ quan trọng khi các thế lực phát xít tại Đức, Ý và Nhật Bản đang cầm quyền và chạy đua vũ trang chuẩn bị cho chiến tranh thế giới. Thời kỳ này đánh dấu sự gia tăng căng thẳng chính trị và các phong trào phản kháng trên toàn cầu.'), ('ent-1b5f7d3a6161e2a8a6b1d86090b4e4fe', 'KHỦNG HOẢNG KINH TẾ THẾ GIỚI', None, 'Khủng hoảng kinh tế thế giới bắt đầu từ năm 1929 đã ảnh hưởng đến nhiều quốc gia, bao gồm cả Pháp và thuộc địa của họ như Đông Dương. Sự suy thoái kinh tế này dẫn đến những chính sách khai thác mạnh mẽ hơn từ thực dân Pháp nhằm bù đắp cho những mất mát trong nền kinh tế của họ.<SEP>Khủng hoảng kinh tế thế giới bắt đầu vào cuối thập niên 1920 và kéo dài suốt những năm 30, đã làm suy yếu nền kinh tế toàn cầu, ảnh hưởng đến các thuộc địa, trong đó có Việt Nam. Chính sách thực dân của Pháp trong Đông Dương chủ yếu nhằm bù đắp thiệt hại do khủng hoảng này gây ra.<SEP>Đời sống nhân dân vào những năm 30 gặp nhiều khó khăn do sự áp bức và khai thác của thực dân Pháp. Nhiều người lao động, đặc biệt là công nhân và nông dân, chịu cảnh thất nghiệp và bóc lột, từ đó dẫn đến sự phẫn nộ và tham gia sâu hơn vào các cuộc đấu tranh vì quyền lợi.'), ('ent-c6aa212e3ea04b2169f1007d1eb8c3f0', 'THỰC DÂN ĐỘC QUYỀN', None, 'Thực dân độc quyền là chính sách mà thực dân Pháp áp đặt lên nền kinh tế thuộc địa, nhằm kiểm soát chặt chẽ các lĩnh vực thương mại, đặc biệt là thuốc phiện và rượu, thu lợi nhuận rất cao từ việc xuất nhập khẩu. Chính sách này góp phần làm tăng thêm sự bất bình trong dân chúng và thúc đẩy phong trào phản kháng.<SEP>Đảng phản động là một trong những đảng phái chính trị hoạt động tại Đông Dương trong thập kỷ 30, thường chống lại những cải cách tiến bộ và các phong trào cách mạng. Họ thường đứng về phía thực dân và có vai trò cản trở sự phát triển của phong trào đấu tranh tại Việt Nam.<SEP>Đảng theo xu hướng cải lương là một trong những tổ chức chính trị tại Đông Dương, hoạt động trong những năm 30, tìm cách cải cách từ bên trong mà không chấm dứt sự cai trị của thực dân. Họ có thể đã khuyến khích những thay đổi nhưng không đủ mạnh để tạo ra đột phá trong phong trào đấu tranh.')]

    for i in all_entities_data:
        print(i[2])
    # Insert or upsert events
    # insert_rows(all_entities_data)
