SinkrOn 



Sinkron : Jurnal dan Penelitian Teknik Informatika Volume 7, Number 4, October 2023 DOI : https://doi.org/10.33395/sinkron.v8i4.12925 

e-ISSN : 2541-2019 p-ISSN : 2541-044X 



has gained traction (Herrera et al., 2019). The foundational importance of a comprehensive knowledge base in supporting such AI implementations cannot be overstated. Technicians depend on it for swift access to pertinent troubleshooting information (Dai, 2022). Modern AI-powered models can produce detailed content for knowledge bases, covering various troubleshooting scenarios(Thomas & J., 2020), thereby simplifying the ticket categorization process (Anwar, 2021). 

However, even with advanced systems, challenges persist. While the implementation of IT software or tools can help manage incoming tickets, there are still bottlenecks to be fixed (Qamili et al., 2018). The correct implementation of algorithms like Random Forest in high-performance computing platforms can also further enhance these processes (Herrera et al., 2019). Moreover, the potential of AI-enabled service chains, which requires the alignment of Service Level Agreements (SLAs) with AI systems, signifies the next frontier in optimizing operational efficiency (Engel et al., 2022). Research suggest with the advancement of AI privacy should also be focused (Elliott & Soifer, 2022), therefore the usage of data during experiment will be redacted based on enterprise security and privacy. 

By leveraging these AI-based tools and models, technicians can access data that's not only accurate but also contextually relevant to the enterprise. The prioritization matrix are created to help with multiple bottlenecks in time management, easy task which takes time to complete (Kc et al., 2017) and the management of prioritization matrix itself (Bugayenko et al., 2023; Obodo, 2018). To tackle this problem simple 3x3 matrix is created based on Impact and Urgency of the ticket based on the ticket description. The result, is to create a models that understand the priority in which should be done now or later. 

Furthermore, as the adoption of AI in various sectors such as business governance (Schneider et al., 2023) and public administration continues to grow, so does the need for continuous research on its potential implications and challenges. 

## **LITERATURE REVIEW** 

The IT support field is constantly adapting to meet technological developments and the need to improve user interactions. Machine learning, with a particular focus on the Random Forest algorithm, plays an important role in these adjustments. In this literature review, we analyze relevant studies, detailing their approach, results, and broader impact. This systematic review aims to shed light on both progress and areas for improvement, paving the way for a clearer understanding of current research gaps. 

<u>Table. 1 Previous Studies which discuss IT Supports and Random Forest Classification</u> 

|Author|Topic|Advantage|Disadvantage|
|---|---|---|---|
|(Ali, 2018)|Automatic Complaints<br>Categorization Using<br>Random Forest and<br>Gradient Boosting|Effective categorization<br>techniques for customer<br>complaints using<br>machine learning.|Specific focus on<br>customer complaints,<br>which might not<br>encompass the entire<br>breadth of IT support<br>issues.|
|(Engel et al., 2022)|SLA-aware operational<br>efficiency in AI-enabled<br>service chains:<br>challenges ahead|AI-driven knowledge<br>base expansion<br>integrated with Random<br>Forest led to operational<br>efficiency improvements<br>in service chains.|<br>The research might not<br>fully account for<br>unexpected challenges<br>arising from integrating<br>AI and SLA in dynamic<br>service environments.|
|(Katuwal & Suganthan,<br>2018)|Enhancing Multi-Class<br>Classification of|Combining Random<br>Forest with other ML|Limited to multi-class<br>problems;the|



*name of corresponding author 



This is a Creative Commons License This work is licensed under a Creative Commons Attribution-NonCommercial 4.0 International License. 

2284 

SinkrOn JRNA 4 NELITIAN TEKNIK INFORMAT! 



<!-- Start of picture text -->
Dataset Acquisition Data Cleaning Feature Selection<br>Dataset taken from GLPI ITSM Unwanted Words, Stop words, Business details Ticket Description, Impact, Urgency<br>Statistical Analysis Transform Ticket Description<br>Apply “Elbow Method” for Clustering Possibility IndoBERT to transform from words to numbers<br>Split Dataset Evaluate Model & Report Model Testing<br>Distinguish Train and Test Data Precision, Recall, and Fi-Score Use Human Input fer Testing<br><!-- End of picture text -->



<!-- Start of picture text -->
(oxoles<br><!-- End of picture text -->

Sinkron : Jurnal dan Penelitian Teknik Informatika Volume 7, Number 4, October 2023 DOI : https://doi.org/10.33395/sinkron.v8i4.12925 

e-ISSN : 2541-2019 p-ISSN : 2541-044X 



provide information on the selection of appropriate methods. Their input helped determine which analysis tool is best suited for developing an automated request prioritization framework. The basis of the analysis is data from the IT ticketing system GLPI, spanning from October 2022 to June 2023. This dataset includes a set of supporting tickets as the basis for the extent investigation. 

Extensive data pre-processing is performed to resolve any inconsistencies or gaps in the data. This step is intended to remove critical business related information and to ensure the reliability of subsequent analyses. Feature extraction is performed post pre-processing the dataset, this includes three selections, Urgency, Impact, and Ticket descriptions. To extract relevant information from these tickets, the IndoBERT model was used. This model, a variant of the BERT architecture adapted to the Indonesian language, is the engine that encodes the textual data of the ticket, converting it into a format suitable for model import. Once encoded, the IndoBERT model generates digital representations that encapsulate the context of textual data. These integrations become necessary for the subsequent classification process. 

The main element of this study is the 3x3 matrix, which is built on the basis of two main dimensions: Impact and urgency. The Impact dimension has been subdivided into: 

1. High: Pertaining to issues with organizational-wide repercussions. 

2. Medium: Referring to challenges localized to particular departments. 

3. Low: Denoting concerns with individual implications. 

On the other hand, the Urgency dimension was demarcated as: 

1. High: Demanding instantaneous resolution. 

2. Medium: Necessitating resolution within a day. 

3. Low: Issues that can be addressed with a broader resolution window. 

|**PR**|**IORITY**|**IMPACT**|||
|---|---|---|---|---|
|IM<br>UR|PACT *<br>GENCY|**Low**<br>**Personal**<br>**Level**|**Medium**<br>**Departme**<br>**nt**<br>**Level**|**High**<br>**Organizati**<br>**onal**<br>**Level**|
|**U**<br>**R**<br>**G**|**Low**<br>**Later date**|1|2|3|
|<br>**E**<br>**N**<br>**C**<br>|**Medium**<br>**Within 24**<br>**hours**|2|3|6|
|**Y**|**High**<br>**Immediately /**<br>**Now**|3|6|9|



Fig. 2 Prioritization Matrix **Source: researcher property** 

By cross-referencing aspects of Impact and Urgency, the matrix provides a systematic approach to prioritizing issues. The priority will be scaled from 1 to 9 in which empower the Urgency levels: 

*name of corresponding author 



This is a Creative Commons License This work is licensed under a Creative Commons Attribution-NonCommercial 4.0 International License. 

2286 

SinkrOn 



SinkrOne URNAL & PENELITIAN TEKNIK INFORMATIKA 



<!-- Start of picture text -->
The Elbow Method<br>8<br>7?<br>6<br>5<br>3s<br>54<br>3<br>2<br>1<br>oOo<br>1 FJ 4a 4 5 6 ra a 9<br>ke<br><!-- End of picture text -->

BY NC 

SinkrO JURNAL &PENELITIAN TEKNIK INFORMATIKA 



<!-- Start of picture text -->
Confusion Matrix for Urgency Metrics<br>- 70<br>° 2 4 4 60<br>50<br>a 40<br>o<br>Ba ) 73 29<br><<br>30<br>20<br>N Oo 32 10<br>0<br>0 1 2<br>Predicted<br><!-- End of picture text -->

OS) 

JURNAL &PENELITIAN TEKNIK INFORMATIKA 



<!-- Start of picture text -->
Classification Report for Urgency Metrics<br>1.0 lmmmm PrecisionRecall<br>fm F1-Score<br>08<br>06<br>2S<br>a<br>o4<br>02<br>0.0<br>1 2 3<br>Categories<br><!-- End of picture text -->



<!-- Start of picture text -->
Confusion Matrix for Impact Metrics<br>- 140<br>o- 141 0) ° 120<br>100<br>80<br>3<br>Ba 8 37 0)<br>2<br>60<br>40<br>n 3 0) 13 20<br>0)r 1' 2r 0)<br>Predicted<br><!-- End of picture text -->



<!-- Start of picture text -->
eC BY NC<br><!-- End of picture text -->

eC BY NC 

JURNAL & PENELITIAN TEKNIK INFORMATIKA 

# SinkrO 



<!-- Start of picture text -->
Classification Report for Urgency Metrics<br>Lo mm Precision<br>ME Recall<br>Mm F1-Score<br>08<br>0.6<br>3<br>0.4<br>0.2<br>0.0<br>1 2 3<br>Categories<br><!-- End of picture text -->



<!-- Start of picture text -->
Word Cloud for Ticket Descriptions without Stopwords<br>Tolongee  “pithan...Rengaturanconnect..|” “iter<br>akSes dapaesp gece: KOMPUL EH<br>3 _ po. OO Clogin*<br>ver tunessT SolEE coreg, sacs Thank Wingakses c pe, 79ntBhs c eS<br>Mohon v5 i " ‘a iol 4. CE<br>CPU instal £ mencetak (5 masuk ee Pogo a<br>Bee ead Ce “eee<br>2 i o<br>TP poo mati® Boni: a a oe<br>ir data ainta e: wenbuka file » Bantuan nya server = 2 —=<br>j. bermasalahw.. akses ke Permintaan °.<br>~ = “iy uka «<br>is pada tertentulll 2 sg ier «uf setelah (Tce<br>io: @) ™ Boombsrus Bc OE a rs file? @ muncul P Ckoneksi<br>. install ERp"ke data Ccenterletor<br><!-- End of picture text -->

LOS BY NC 

SinkrOn 





Sinkron : Jurnal dan Penelitian Teknik Informatika Volume 7, Number 4, October 2023 e-ISSN : 2541-2019 DOI : https://doi.org/10.33395/sinkron.v8i4.12925 p-ISSN : 2541-044X 

Schneider, J., Abraham, R., Meske, C., & Vom Brocke, J. (2023). Artificial Intelligence Governance For Businesses. Information Systems Management, 40(3), 229–249. https://doi.org/10.1080/10580530.2022.2085825 

Silva, S., Pereira, R., & Ribeiro, R. (2018). Machine learning in incident categorization automation. 2018 13th Iberian Conference on Information Systems and Technologies (CISTI), 1–6. https://doi.org/10.23919/CISTI.2018.8399244 

Thomas, B., & J., C. (2020). Random forest application on cognitive level classification of E-learning content. International Journal of Electrical and Computer Engineering (IJECE), 10(4), 4372. https://doi.org/10.11591/ijece.v10i4.pp4372-4380 

*name of corresponding author 



This is a Creative Commons License This work is licensed under a Creative Commons Attribution-NonCommercial 4.0 International License. 

2293 

